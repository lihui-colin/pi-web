// Host output uses Paseo's 5ms leading/trailing policy after headless parsing.
// Only strings already committed to the screen may enter this bounded buffer.
function createDshHostOutputBatcher(host) {
	let chunks = [], bytes = 0, encodedBytes = 0, timer, lastFlushAt;
	let failure;
	const clearTimer = () => {
		if (timer !== void 0) clearTimeout(timer);
		timer = void 0;
	};
	const frameBytes = dataBytes => Buffer.byteLength(JSON.stringify({ type: "output", sequence: host.sequence + 1, data: "" }), "utf8") + dataBytes;
	const flush = () => {
		clearTimer();
		if (failure !== void 0) throw failure;
		if (chunks.length === 0) return;
		const data = chunks.length === 1 ? chunks[0] : chunks.join("");
		chunks = [];
		bytes = 0;
		encodedBytes = 0;
		lastFlushAt = Date.now();
		host.broadcast({ type: "output", sequence: ++host.sequence, data });
	};
	return {
		handle(data) {
			if (failure !== void 0) throw failure;
			if (data.length === 0) return;
			// The class field creates this batcher before the constructor assigns the budget.
			// Large budgets need no re-encoding: JSON is at most 6x UTF-8 plus this <=64B header.
			const checkFrameBudget = host.maxBufferedBytes < 65536 * 6 + 64;
			const size = Buffer.byteLength(data, "utf8");
			// A huge original chunk keeps upstream handling without another huge JSON copy.
			if (size >= 65536 || size >= host.maxBufferedBytes) {
				flush();
				chunks.push(data);
				return flush();
			}
			// Per-chunk JSON counts include escaping and conservatively count split surrogates.
			const encodedSize = checkFrameBudget ? Buffer.byteLength(JSON.stringify(data), "utf8") - 2 : 0;
			if (bytes + size > 65536 || chunks.length >= 128
				|| checkFrameBudget && frameBytes(encodedBytes + encodedSize) > host.maxBufferedBytes) flush();
			chunks.push(data);
			bytes += size;
			encodedBytes += encodedSize;
			if (bytes >= 65536 || chunks.length >= 128 || checkFrameBudget && frameBytes(encodedBytes) > host.maxBufferedBytes) return flush();
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
