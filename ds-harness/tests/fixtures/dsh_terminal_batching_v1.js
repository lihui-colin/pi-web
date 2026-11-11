// Connected terminal render batching. Physical Gateway inbox remains unchanged.
// Keep this function self-contained: tests execute the exact injected consumer.
async function dshConsumeTerminalBatched(stream) {
    const maxBytes = 2 * 1024 * 1024;
    const maxRecords = 4096;
    const maxBatchBytes = 64 * 1024;
    const encoder = new TextEncoder();
    let generation = 0, sequence = 0, bytes = 0, records = 0;
    let queue = [], active, pumping, stopped = false, overflowed = false, unlisten;
    let control = false, terminal;
    const terminalGeneration = entry => terminal?.generation === entry.generation;
    const live = () => !stopped && this.stream === stream;
    const clearQueued = () => {
        queue = [];
        bytes = active?.bytes ?? 0;
        records = active?.records ?? 0;
    };
    const cancelRender = () => {
        if (this.pendingRender !== undefined && active?.revision === this.pendingRender.revision) {
            const pending = this.pendingRender;
            this.pendingRender = undefined;
            pending.resolve(); // Cancellation releases the waiter; never report a parse ACK.
        }
    };
    const fail = (error) => {
        if (!live()) return;
        stopped = true;
        control = false;
        clearQueued();
        cancelRender();
        this.fail(error);
        this.detach(); // No automatic replay or recovery without a fresh explicit attachment.
    };
    const drain = async () => {
        while (live() && queue.length) {
            const entry = queue.shift();
            if (entry.frame.type === 'output') {
                const parts = [entry.frame.data];
                let dataBytes = entry.dataBytes;
                while (!entry.sealed && queue.length && queue[0].generation === entry.generation
                    && queue[0].frame.type === 'output'
                    && dataBytes + queue[0].dataBytes <= maxBatchBytes) {
                    const next = queue.shift();
                    parts.push(next.frame.data);
                    dataBytes += next.dataBytes;
                    entry.bytes += next.bytes;
                    entry.records += next.records;
                    entry.sealed = next.sealed;
                    entry.frame = { ...next.frame, data: '' };
                }
                entry.frame = { ...entry.frame, data: parts.join('') };
            }
            active = entry;
            try {
                if (entry.signal.aborted && !terminalGeneration(entry)) continue;
                const frame = entry.frame;
                if (frame.type !== 'output') {
                    this.inventory.update(frame.info);
                    this.patch({ info: frame.info, title: frame.info.title, phase: 'connected',
                        writable: control && frame.info.state === 'running' && frame.writable });
                }
                if (frame.type !== 'state') {
                    const revision = ++this.revision;
                    entry.revision = revision;
                    await new Promise(resolve => {
                        this.pendingRender = { revision, resolve };
                        this.patch({ render: { revision, frame } });
                        if (entry.signal.aborted && !terminalGeneration(entry)) cancelRender();
                    });
                }
            } finally {
                bytes -= entry.bytes;
                records -= entry.records;
                active = undefined;
            }
        }
    };
    const kick = () => {
        if (pumping !== undefined) return;
        pumping = drain().catch(fail).finally(() => {
            pumping = undefined;
            if (live() && queue.length) kick();
        });
    };
    const finishTerminal = async () => {
        while (pumping !== undefined) await pumping;
        if (!live() || terminal === undefined) return;
        if (terminal.info.state === 'exited') this.patch({ phase: 'closed', writable: false });
        else fail(new Error(terminal.info.error || 'Terminal process failed'));
    };
    try {
        let turns = 0;
        for await (const item of stream) {
            if (!live()) break;
            if (item.signal.aborted) continue;
            const frame = item.value;
            if (generation !== item.generation) {
                if (frame.type !== 'snapshot')
                    throw new TerminalViewError('invalidOutput', 'Terminal output generation is missing its screen snapshot');
                unlisten?.();
                clearQueued();
                cancelRender();
                generation = item.generation;
                terminal = undefined;
                sequence = frame.sequence;
                control = frame.info.state === 'running' && frame.writable;
                const aborted = () => {
                    if (generation !== item.generation) return;
                    control = false;
                    // RemoteStream aborts its generation in finally even on normal EOF.
                    // A validated ingress terminal state makes its preceding bytes drainable.
                    if (live() && terminalGeneration(item) && !overflowed) {
                        this.patch({ writable: false });
                        return;
                    }
                    clearQueued();
                    cancelRender();
                    if (live()) this.patch({ phase: 'disconnected', writable: false, render: undefined });
                };
                item.signal.addEventListener('abort', aborted, { once: true });
                unlisten = () => item.signal.removeEventListener('abort', aborted);
                item.accept(); // Opening-baseline acceptance, never a render acknowledgement.
            } else if (frame.type === 'output') {
                if (frame.sequence !== sequence + 1)
                    throw new TerminalViewError('invalidOutput', 'Terminal output sequence has a gap');
                sequence = frame.sequence;
            } else if (frame.type === 'snapshot') {
                throw new TerminalViewError('invalidOutput', 'Unexpected terminal screen snapshot');
            }
            if (frame.type === 'ack') {
                // Preserve an ACK as an adjacency barrier without retaining it in the render queue.
                if (queue.length) queue[queue.length - 1].sealed = true;
                const attachment = this.attachment;
                if (attachment === undefined)
                    throw new TerminalViewError('invalidOutput', 'Terminal acknowledgement has no attachment');
                const pending = attachment.pending.get(frame.sequence);
                if (frame.sequence !== attachment.acknowledged + 1 || pending === undefined)
                    throw new TerminalViewError('invalidOutput', 'Terminal input acknowledgement is out of order');
                attachment.acknowledged = frame.sequence;
                attachment.bytes -= pending.inputBytes;
                attachment.bufferedBytes -= pending.frameBytes;
                attachment.inFlightBytes -= pending.frameBytes;
                attachment.pending.delete(frame.sequence);
                if (frame.refusal !== undefined) {
                    control = false;
                    this.patch({ writable: false });
                }
                this.flushInput(attachment);
            } else {
                if (frame.type === 'state') {
                    control = frame.info.state === 'running' && frame.writable;
                    if (!control) this.patch({ writable: false });
                }
                if ((frame.type === 'state' || frame.type === 'snapshot') && frame.info.state !== 'running') {
                    terminal = { generation, info: frame.info };
                }
                const size = encoder.encode(JSON.stringify(frame)).byteLength;
                if (bytes + size > maxBytes || records + 1 > maxRecords) {
                    overflowed = true;
                    throw new Error('Terminal output exceeded its render buffer; reconnect to recover the current screen. Pending input was not replayed.');
                }
                const entry = { frame, generation, signal: item.signal, bytes: size, records: 1,
                    dataBytes: frame.type === 'output' ? encoder.encode(frame.data).byteLength : 0 };
                bytes += size;
                records++;
                queue.push(entry);
                kick();
            }
            // Allow timers, keyboard events and xterm callbacks through even with a ready inbox.
            if (++turns % 128 === 0) await new Promise(resolve => setTimeout(resolve, 0));
        }
        await finishTerminal();
    } catch (error) {
        // Only the domain's normal EOF marker may wait for the final screen.
        // A sequence/ACK/protocol failure after terminal state still fails immediately.
        if (!overflowed && terminal !== undefined && error?.code === 'terminal/view'
            && error?.details?.issue === 'attachmentEnded') await finishTerminal();
        else fail(error);
    } finally {
        stopped = true;
        unlisten?.();
        clearQueued();
        cancelRender();
        if (pumping !== undefined) await pumping;
    }
}
