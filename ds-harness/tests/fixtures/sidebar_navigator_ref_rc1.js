		const RESIZE_STEP = 20;
// Exact navigator ref excerpt from the local rc.1 FileNavigator, before its
// cwd/open early return; wrapped only to make the fixture valid JavaScript.
function navigatorRefFixture(react, navigatorDrawn, paneId, page, mode) {
			const navigatorRef = (0, react.useCallback)((element) => {
				navigatorDrawn(paneId, element, !page);
			}, [
				navigatorDrawn,
				paneId,
				page
			]);
return navigatorRef;
}
