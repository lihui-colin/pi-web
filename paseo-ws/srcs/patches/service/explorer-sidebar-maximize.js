/* The dock, including every tab and its header, expands inside its workspace. */
var paseoExplorerMaximizeContext;
var paseoExplorerSuspendedWorkspaces = new Set();
var paseoExplorerSuspensionListeners = new Set();
function paseoSubscribeExplorerSuspension(listener) {
  paseoExplorerSuspensionListeners.add(listener);
  return () => paseoExplorerSuspensionListeners.delete(listener);
}
function paseoSetExplorerSuspension(workspaceKey, suspended) {
  if (!workspaceKey || paseoExplorerSuspendedWorkspaces.has(workspaceKey) === suspended) return;
  if (suspended) paseoExplorerSuspendedWorkspaces.add(workspaceKey);
  else paseoExplorerSuspendedWorkspaces.delete(workspaceKey);
  for (const listener of paseoExplorerSuspensionListeners) listener();
}
function paseoExplorerSuspensionServerSnapshot() { return false; }
function paseoGetExplorerMaximizeContext(React) {
  return paseoExplorerMaximizeContext ??= React.createContext(null);
}
function createPaseoExplorerFrame(React, Frame, useRetainedPanelActive) {
  const Context = paseoGetExplorerMaximizeContext(React);
  return function PaseoExplorerFrame(props) {
    const [state, setState] = React.useState(null);
    const workspaceKey = props.persistenceKey;
    const canMaximize = props.presentation === 'dock';
    // Workspace screens stay mounted in the retained deck. Its activity context
    // can deactivate before a cached screen's route-focus props are refreshed.
    const retainedActive = useRetainedPanelActive();
    const visible = retainedActive && props.isWorkspaceActive && props.isOpen;
    const maximized = Boolean(canMaximize && visible && state?.workspaceKey === workspaceKey && state.maximized);
    const toggle = React.useCallback(() => {
      if (!canMaximize || !visible) return;
      setState(current => ({ workspaceKey, maximized: current?.workspaceKey !== workspaceKey || !current.maximized }));
    }, [workspaceKey, canMaximize, visible]);
    React.useLayoutEffect(() => {
      if (!canMaximize || !visible || state?.workspaceKey !== workspaceKey) setState(null);
    }, [canMaximize, visible, workspaceKey, state?.workspaceKey]);
    React.useLayoutEffect(() => {
      paseoSetExplorerSuspension(workspaceKey, maximized);
      return () => paseoSetExplorerSuspension(workspaceKey, false);
    }, [workspaceKey, maximized]);
    const controls = React.useMemo(() => ({ canMaximize, maximized, toggle }), [canMaximize, maximized, toggle]);
    return React.createElement(Context.Provider, { value: controls },
      React.createElement(Frame, { ...props, paseoExplorerMaximized: maximized }));
  };
}
function createPaseoExplorerAwareMain(React, Main, RetainedPanelActivity) {
  return function PaseoExplorerAwareMain(props) {
    const snapshot = React.useCallback(() => paseoExplorerSuspendedWorkspaces.has(props.workspaceKey), [props.workspaceKey]);
    const suspended = React.useSyncExternalStore(paseoSubscribeExplorerSuspension, snapshot, paseoExplorerSuspensionServerSnapshot);
    // Keep the middle pane mounted and sized, but exclude covered controls from
    // browser focus and disable its existing pane/retained keyboard scopes.
    return React.createElement('div', {
      style: { display: 'contents' }, inert: suspended, 'aria-hidden': suspended || undefined,
      'data-testid': 'explorer-main-interaction-scope',
    }, React.createElement(RetainedPanelActivity, { active: !suspended },
      React.createElement(Main, { ...props, isWorkspaceFocused: props.isWorkspaceFocused && !suspended })));
  };
}
function createPaseoExplorerDock(React, Dock, MaximizeButton, View) {
  const Context = paseoGetExplorerMaximizeContext(React);
  return function PaseoExplorerDock(props) {
    const controls = React.useContext(Context);
    const headerAction = controls?.canMaximize ? React.createElement(View, {
      style: { flexDirection: 'row', alignItems: 'center' }, testID: 'explorer-sidebar-controls',
    }, React.createElement(MaximizeButton, {
      showMaximizeAction: true, paneMaximized: controls.maximized,
      onTogglePaneMaximized: controls.toggle,
    }), props.headerAction) : props.headerAction;
    return React.createElement(Dock, { ...props, headerAction });
  };
}
