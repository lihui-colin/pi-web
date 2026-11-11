		function TerminalScreen({ state, model, visible, label, theme }) {
			const element = (0, react.useRef)(null);
			const terminal = (0, react.useRef)();
			const fit = (0, react.useRef)();
			const colors = (0, react.useRef)();
			const lastRevision = (0, react.useRef)(0);
			const fontFamily = terminalFontFamily(theme.fontFamilies.terminal);
			const fontSize = theme.fontSizes.terminal;
			const current = (0, react.useRef)({
				state,
				visible,
				fontFamily,
				fontSize
			});
			current.current = {
				state,
				visible,
				fontFamily,
				fontSize
			};
			(0, react.useLayoutEffect)(() => {
				const node = element.current;
				const xterm = new import_xterm.Terminal({
					minimumContrastRatio: 4.5,
					cursorBlink: true,
					fontSize: current.current.fontSize,
					fontFamily: current.current.fontFamily,
					scrollback: current.current.state.environment?.scrollback ?? 0
				});
				const addon = new import_addon_fit.FitAddon();
				xterm.loadAddon(addon);
				xterm.open(node);
				const palette = new TerminalTheme(xterm);
				colors.current = palette;
				const cursor = observeTerminalCursor(xterm, node, () => palette.cursor);
				xterm.textarea?.setAttribute("aria-label", label);
				terminal.current = xterm;
				fit.current = addon;
				lastRevision.current = 0;
				const input = xterm.onData((data) => {
					model.write(data);
				});
				const measure = () => {
					if (!current.current.visible || !current.current.state.writable || node.clientWidth === 0 || node.clientHeight === 0) return;
					fitScreen(xterm, addon, current.current.state, model);
				};
				const observer = new ResizeObserver(measure);
				observer.observe(node);
				return () => {
					observer.disconnect();
					input.dispose();
					cursor.dispose();
					palette.dispose();
					xterm.dispose();
					terminal.current = void 0;
					fit.current = void 0;
				};
			}, [model]);
			(0, react.useLayoutEffect)(() => {
				const style = getComputedStyle(element.current);
				colors.current.update(style.backgroundColor, style.color);
			}, [theme, model]);
			(0, react.useLayoutEffect)(() => {
				const xterm = terminal.current;
				if (xterm.options.fontFamily === fontFamily && xterm.options.fontSize === fontSize) return;
				xterm.options.fontFamily = fontFamily;
				xterm.options.fontSize = fontSize;
				const { state: live, visible: shown } = current.current;
				if (shown && live.writable && element.current.clientWidth && element.current.clientHeight) fitScreen(xterm, fit.current, live, model);
			}, [
				fontFamily,
				fontSize,
				model
			]);
			(0, react.useLayoutEffect)(() => {
				const xterm = terminal.current;
				const render = state.render;
				if (render === void 0 || render.revision <= lastRevision.current) return;
				lastRevision.current = render.revision;
				if (render.frame.type === "snapshot") {
					xterm.reset();
					xterm.resize(render.frame.info.cols, render.frame.info.rows);
				}
				xterm.write(render.frame.type === "snapshot" ? render.frame.screen : render.frame.data, () => {
					model.acknowledge(render.revision);
				});
			}, [state.render, model]);
			(0, react.useLayoutEffect)(() => {
				const xterm = terminal.current;
				xterm.options.disableStdin = !state.writable;
				if (visible && state.writable && element.current?.clientWidth && element.current.clientHeight) fitScreen(xterm, fit.current, state, model);
				else if (state.info !== void 0 && !state.writable) xterm.resize(state.info.cols, state.info.rows);
			}, [
				visible,
				state.writable,
				state.info?.cols,
				state.info?.rows,
				model
			]);
			(0, react.useEffect)(() => {
				terminal.current.textarea?.setAttribute("aria-label", label);
			}, [label]);
			(0, react.useEffect)(() => {
				if (visible && state.writable) terminal.current.focus();
			}, [visible, state.writable]);
			return (0, react_jsx_runtime.jsx)("div", {
				className: terminal_module_css_default.screen,
				ref: element
			});
		}
		/** Built-in terminal stack placed after the user's normalized list. */
		const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
		function terminalFontFamily(list) {
			return list === "" ? TERMINAL_FONT_STACK : `${list}, ${TERMINAL_FONT_STACK}`;
		}
		function fitScreen(xterm, fit, state, model) {
			const dimensions = fit.proposeDimensions();
			const environment = state.environment;
			if (dimensions === void 0 || environment === void 0) return;
			const cols = Math.min(dimensions.cols, environment.maxCols);
			const rows = Math.min(dimensions.rows, environment.maxRows);
			if (cols < 2 || rows < 1) return;
			xterm.resize(cols, rows);
			model.resize(cols, rows);
		}