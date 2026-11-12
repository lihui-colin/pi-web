// Native ComposerContentEditable from @deepseek-ai/dsh-client-ui-conversation 0.2.2-rc.1.
function ComposerContentEditable({ editor, editable, ...rest }) {
  const ref = (0, react.useRef)(null);
  (0, react.useLayoutEffect)(() => {
    const el = ref.current;
    if (editor === null || el === null) return;
    editor.setRootElement(el);
    return () => { editor.setRootElement(null); };
  }, [editor]);
  (0, react.useLayoutEffect)(() => {
    if (editor !== null) editor.setEditable(editable);
  }, [editor, editable]);
  return (0, react_jsx_runtime.jsx)("div", {
    ref,
    contentEditable: editor !== null && editable,
    suppressContentEditableWarning: true,
    role: "textbox",
    "aria-multiline": "true",
    "data-composer-input": true,
    ...rest
  });
}
