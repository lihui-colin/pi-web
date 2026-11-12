// Host output uses Paseo's 5ms leading/trailing policy after headless parsing.
// Only strings already committed to the screen may enter this bounded buffer.
function createDshHostOutputBatcher(host) {
	let chunks = [], bytes = 0, timer, lastFlushAt;
	let failure;
	const clearTimer = () => {
		if (timer !== void 0) clearTimeout(timer);
		timer = void 0;
	};
	const flush = () => {
		clearTimer();
		if (failure !== void 0) throw failure;
		if (chunks.length === 0) return;
		const data = chunks.length === 1 ? chunks[0] : chunks.join("");
		chunks = [];
		bytes = 0;
		lastFlushAt = Date.now();
		host.broadcast({ type: "output", sequence: ++host.sequence, data });
	};
	return {
		handle(data) {
			if (failure !== void 0) throw failure;
			if (data.length === 0) return;
			const size = Buffer.byteLength(data, "utf8");
			// Flush before adding an oversized chunk; never retain an unbounded copy.
			if (bytes + size > 65536 || chunks.length >= 128) flush();
			chunks.push(data);
			bytes += size;
			if (bytes >= 65536 || chunks.length >= 128) return flush();
			if (timer === void 0) {
				if (lastFlushAt === void 0 || Date.now() - lastFlushAt >= 5) return flush();
				timer = setTimeout(() => {
					timer = void 0;
					// Queue behind all outstanding headless writes. Observe rejection:
					// background broadcast errors must reach followers and later barriers.
					host.enqueue(flush).catch((error) => {
						failure = error instanceof Error ? error : new Error(String(error));
						host.info = { ...host.info, state: "failed", error: failure.message };
						for (const follower of host.followers) follower.fail(failure);
					});
				}, 5);
			}
		},
		flush,
		dispose() { clearTimer(); flush(); }
	};
}
