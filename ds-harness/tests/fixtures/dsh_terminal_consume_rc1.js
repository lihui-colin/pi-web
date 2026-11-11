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