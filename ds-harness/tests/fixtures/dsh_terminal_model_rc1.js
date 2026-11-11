		var TerminalView = class {
			sessionId;
			remote;
			gateway;
			inventory;
			id;
			createWhenMissing;
			shellPath;
			retain;
			/** Observable controls, process metadata and the next screen update awaiting acknowledgement. */
			state = (0, _deepseek_ai_dsh_client_store.createSnapshotStore)({
				phase: "idle",
				writable: false
			});
			lifetime = new AbortController();
			stream;
			mounted = false;
			attachment;
			pendingRender;
			revision = 0;
			creation;
			loading;
			closing;
			detaching = /* @__PURE__ */ new Set();
			/**
			* @param sessionId - Session owning the terminal.
			* @param remote - typed terminal Remote operations.
			* @param gateway - reconnecting stream factory.
			* @param inventory - Session-owned terminal list shared by all views.
			* @param id - Host terminal identity, reused when recovering an item from its Session list.
			* @param createWhenMissing - allow allocation only for a new tab, never a listed terminal.
			* @param shellPath - explicit shell chosen at the guide; omission uses the remembered available shell.
			* @param retain - window hold acknowledgement required before output attachment.
			*/
			constructor(sessionId, remote, gateway, inventory, id, createWhenMissing = true, shellPath, retain) {
				this.sessionId = sessionId;
				this.remote = remote;
				this.gateway = gateway;
				this.inventory = inventory;
				this.id = id;
				this.createWhenMissing = createWhenMissing;
				this.shellPath = shellPath;
				this.retain = retain;
			}
			/**
			* Attach the DOM lifetime, starting the chosen shell or reconnecting the saved process.
			* @returns a detach callback that leaves the terminal process alive.
			*/
			mount() {
				this.mounted = true;
				const state = this.state.getSnapshot();
				if (state.phase === "idle") this.refresh();
				else if (state.info !== void 0 && state.phase !== "failed" && state.phase !== "closed") this.connect();
				return () => {
					this.mounted = false;
					this.detach();
				};
			}
			/**
			* Start or explicitly retry this tab, sharing Session discovery with other views.
			* New identities allocate directly; confirmed or restored terminals cannot be replaced.
			* @returns after environment lookup and creation or recovery settle.
			*/
			refresh() {
				if (this.creation !== void 0) return this.creation;
				if (this.loading !== void 0) return this.loading;
				if (this.closing !== void 0 || this.lifetime.signal.aborted) return Promise.resolve();
				const retry = this.state.getSnapshot().phase !== "idle";
				this.patch({
					phase: "loading",
					error: void 0,
					issue: void 0
				});
				this.loading = (async () => {
					const [environment, available] = await Promise.all([this.remote.environment(this.sessionId, this.lifetime.signal), this.createWhenMissing ? void 0 : this.inventory.read(retry)]);
					if (this.stopped()) return;
					this.patch({ environment: valueOf(environment) });
					const info = available?.get(this.id);
					if (info !== void 0) this.adopt(info);
					else if (this.createWhenMissing) {
						let path = this.shellPath;
						if (path === void 0) {
							const shells = valueOf(await this.remote.shells(this.sessionId, this.lifetime.signal));
							const previous = preferredShell();
							path = shells.find((shell) => shell.path === previous)?.path ?? shells[0]?.path;
						}
						if (this.stopped()) return;
						if (path !== void 0) rememberShell(path);
						await this.create(valueOf(environment), path);
					} else throw new TerminalViewError("missingTerminal");
				})().catch((error) => {
					this.fail(error);
				}).finally(() => {
					this.loading = void 0;
				});
				return this.loading;
			}
			stopped() {
				return this.lifetime.signal.aborted || this.closing !== void 0;
			}
			async create(environment, shellPath) {
				this.patch({
					phase: "creating",
					error: void 0,
					issue: void 0
				});
				this.creation = (async () => {
					const info = valueOf(await this.remote.create(this.sessionId, {
						id: this.id,
						...shellPath === void 0 ? {} : { shellPath },
						cols: Math.min(80, environment.maxCols),
						rows: Math.min(24, environment.maxRows)
					}, this.lifetime.signal));
					if (!this.lifetime.signal.aborted) {
						this.inventory.update(info);
						this.adopt(info);
					}
				})().catch((error) => {
					this.fail(error);
				}).finally(() => {
					this.creation = void 0;
				});
				await this.creation;
			}
			adopt(info) {
				this.createWhenMissing = false;
				this.patch({
					info,
					title: info.title
				});
				if (this.retain === void 0) {
					if (this.mounted && this.closing === void 0) this.connect();
					return;
				}
				this.retain(this.lifetime.signal).then(() => {
					if (this.mounted && this.closing === void 0) this.connect();
				}).catch((error) => {
					if (!this.stopped()) this.fail(error);
				});
			}
			/** Reattach with a fresh screen and regain input control. */
			connect() {
				const info = this.state.getSnapshot().info;
				if (info === void 0 || !this.mounted || this.closing !== void 0 || this.lifetime.signal.aborted) return;
				this.detach();
				const stream = this.gateway.$stream({
					name: "Browser terminal output",
					open: async function* (signal) {
						await this.retain?.(signal);
						signal.throwIfAborted();
						const handle = this.remote.attach(this.sessionId, info.id, signal);
						const attachment = {
							handle,
							signal,
							sequence: 0,
							acknowledged: 0,
							pending: /* @__PURE__ */ new Map(),
							queued: new Deque(),
							window: void 0,
							bytes: 0,
							bufferedBytes: 0,
							inFlightBytes: 0
						};
						this.attachment = attachment;
						try {
							for await (const frame of handle) {
								if (frame.type === "snapshot") attachment.window = frame.inputWindow;
								yield frame;
							}
						} finally {
							if (this.attachment === attachment) this.attachment = void 0;
						}
					}.bind(this),
					ended: () => new TerminalViewError("attachmentEnded"),
					carrierFailed: () => {
						if (this.stream === stream) this.patch({
							phase: "disconnected",
							writable: false
						});
					}
				});
				this.stream = stream;
				this.patch({
					phase: "connecting",
					writable: false,
					error: void 0,
					issue: void 0,
					render: void 0
				});
				this.consume(stream);
			}
			/**
			* Release the next stream item after xterm has parsed this frame.
			* @param revision - locally delivered render revision.
			*/
			acknowledge(revision) {
				if (this.pendingRender?.revision !== revision) return;
				this.pendingRender.resolve();
				this.pendingRender = void 0;
			}
			/**
			* Queue input within the raw UTF-8 and encoded-frame budgets, waiting for carrier capacity.
			* @param data - input from the terminal emulator; never replayed after disconnection.
			*/
			write(data) {
				const state = this.state.getSnapshot();
				const attachment = this.attachment;
				if (!state.writable || state.info === void 0 || attachment === void 0 || attachment.signal.aborted) return;
				if (data.length === 0) return;
				const bytes = new TextEncoder().encode(data).byteLength;
				if (attachment.bytes + bytes > (state.environment?.maxInputBytes ?? 0)) {
					this.failInput(new TerminalViewError("inputFull"));
					return;
				}
				this.send(attachment, {
					type: "write",
					sequence: attachment.sequence + 1,
					data
				}, bytes);
			}
			/**
			* Resize only from the currently writable view, ordered with keyboard input.
			* @param cols - measured column count.
			* @param rows - measured row count.
			*/
			resize(cols, rows) {
				const state = this.state.getSnapshot();
				const attachment = this.attachment;
				if (!state.writable || state.info === void 0 || attachment === void 0 || attachment.signal.aborted) return;
				if (state.info.cols === cols && state.info.rows === rows) return;
				cols = Math.min(cols, state.environment?.maxCols ?? cols);
				rows = Math.min(rows, state.environment?.maxRows ?? rows);
				this.send(attachment, {
					type: "resize",
					sequence: attachment.sequence + 1,
					cols,
					rows
				}, 0);
			}
			send(attachment, command, bytes) {
				const frameBytes = new TextEncoder().encode(JSON.stringify(command)).byteLength + (attachment.window?.frameOverheadBytes ?? 0);
				if (attachment.bufferedBytes + frameBytes > (this.state.getSnapshot().environment?.maxBufferedBytes ?? 0) || attachment.window !== void 0 && frameBytes > attachment.window.maxBytes) {
					this.failInput(new TerminalViewError("inputFull"));
					return;
				}
				attachment.queued.pushBack({
					command,
					inputBytes: bytes,
					frameBytes
				});
				attachment.sequence = command.sequence;
				attachment.bytes += bytes;
				attachment.bufferedBytes += frameBytes;
				this.flushInput(attachment);
			}
			flushInput(attachment) {
				while (this.attachment === attachment && !attachment.signal.aborted && this.state.getSnapshot().writable) {
					const next = attachment.queued.popFront();
					if (next === void 0) return;
					if (attachment.window !== void 0 && attachment.inFlightBytes + next.frameBytes > attachment.window.maxBytes) {
						attachment.queued.pushFront(next);
						return;
					}
					try {
						attachment.handle.send(next.command);
					} catch (error) {
						this.failInput(error);
						return;
					}
					attachment.pending.set(next.command.sequence, {
						inputBytes: next.inputBytes,
						frameBytes: next.frameBytes
					});
					attachment.inFlightBytes += next.frameBytes;
				}
			}
			failInput(error) {
				this.fail(error);
				this.detach();
			}
			/**
			* Update the Host terminal's display name.
			* @param title - user-entered terminal title.
			* @returns after the rename settles and its result is reflected in view state.
			*/
			async rename(title) {
				if (title.trim() === this.state.getSnapshot().title || this.lifetime.signal.aborted) return;
				try {
					valueOf(await this.remote.rename(this.sessionId, this.id, title));
					if (this.stopped()) return;
					const current = this.state.getSnapshot().info;
					if (current !== void 0) this.inventory.update({
						...current,
						title: title.trim()
					});
					this.patch({
						...current === void 0 ? {} : { info: {
							...current,
							title: title.trim()
						} },
						title: title.trim()
					});
				} catch (error) {
					this.fail(error);
				}
			}
			/**
			* Explicitly terminate this view's process independently of its DOM lifetime.
			* @returns after Host process cleanup succeeds; failures remain retryable by the owner.
			*/
			close() {
				if (this.closing !== void 0) return this.closing;
				this.patch({
					phase: "closing",
					writable: false,
					error: void 0,
					issue: void 0
				});
				this.detach();
				this.closing = (async () => {
					await this.creation;
					valueOf(await this.remote.close(this.sessionId, this.id));
					this.inventory.remove(this.id);
					this.detach();
					this.patch({
						phase: "closed",
						writable: false
					});
				})().catch((error) => {
					this.closing = void 0;
					this.fail(error);
					throw error;
				});
				return this.closing;
			}
			/**
			* Stop Client work on plugin unload without closing Host terminals.
			* @returns after active and previously detached stream iterators have closed.
			*/
			async dispose() {
				this.mounted = false;
				this.lifetime.abort();
				this.detach();
				await Promise.all(this.detaching);
			}
			detach() {
				const previous = this.stream;
				this.stream = void 0;
				this.attachment = void 0;
				this.pendingRender?.resolve();
				this.pendingRender = void 0;
				if (previous !== void 0) {
					const cleanup = previous.dispose().finally(() => {
						this.detaching.delete(cleanup);
					});
					this.detaching.add(cleanup);
				}
			}
			async consume(stream) {
				let generation = 0;
				let sequence = 0;
				try {
					for await (const item of stream) {
						if (this.stream !== stream) return;
						const frame = item.value;
						if (generation !== item.generation) {
							if (frame.type !== "snapshot") throw new TerminalViewError("invalidOutput", "Terminal output generation is missing its screen snapshot");
							generation = item.generation;
							sequence = frame.sequence;
							item.accept();
						} else if (frame.type === "output") {
							if (frame.sequence !== sequence + 1) throw new TerminalViewError("invalidOutput", "Terminal output sequence has a gap");
							sequence = frame.sequence;
						} else if (frame.type === "snapshot") throw new TerminalViewError("invalidOutput", "Unexpected terminal screen snapshot");
						if (frame.type === "ack") {
							const attachment = this.attachment;
							/* v8 ignore next -- the physical opener retains its handle until this consumer advances. */
							if (attachment === void 0) throw new TerminalViewError("invalidOutput", "Terminal acknowledgement has no attachment");
							const pending = attachment.pending.get(frame.sequence);
							if (frame.sequence !== attachment.acknowledged + 1 || pending === void 0) throw new TerminalViewError("invalidOutput", "Terminal input acknowledgement is out of order");
							attachment.acknowledged = frame.sequence;
							attachment.bytes -= pending.inputBytes;
							attachment.bufferedBytes -= pending.frameBytes;
							attachment.inFlightBytes -= pending.frameBytes;
							attachment.pending.delete(frame.sequence);
							if (frame.refusal !== void 0) this.patch({ writable: false });
							this.flushInput(attachment);
							continue;
						}
						if (frame.type !== "output") {
							this.inventory.update(frame.info);
							this.patch({
								info: frame.info,
								title: frame.info.title,
								phase: "connected",
								writable: frame.info.state === "running" && frame.writable
							});
						}
						if (frame.type !== "state") {
							const revision = ++this.revision;
							await new Promise((resolve) => {
								this.pendingRender = {
									revision,
									resolve
								};
								const aborted = () => {
									this.acknowledge(revision);
								};
								item.signal.addEventListener("abort", aborted, { once: true });
								this.pendingRender.resolve = () => {
									item.signal.removeEventListener("abort", aborted);
									resolve();
								};
								this.patch({ render: {
									revision,
									frame
								} });
								if (item.signal.aborted) aborted();
							});
						}
					}
				} catch (error) {
					if (this.stream === stream) if (this.state.getSnapshot().info?.state === "exited") this.patch({
						phase: "closed",
						writable: false
					});
					else this.fail(error);
				}
			}
			patch(patch) {
				if (this.lifetime.signal.aborted) return;
				this.state.set({
					...this.state.getSnapshot(),
					...patch
				});
			}
			fail(error) {
				const failure = remoteErrorOf(error);
				const issue = failure?.code === "terminal/view" ? failure.details.issue : failure?.code === "terminal/limit-reached" ? "terminalLimit" : failure?.code === "terminal/unavailable" ? "missingTerminal" : void 0;
				if (!this.stopped() && issue === "missingTerminal") this.inventory.remove(this.id);
				this.patch({
					phase: error instanceof _deepseek_ai_dsh_api_gateway_client.RemoteStreamCarrierError ? "disconnected" : "failed",
					writable: false,
					issue,
					error: error instanceof Error ? error.message : String(error)
				});
			}
		};