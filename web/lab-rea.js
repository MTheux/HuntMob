// Decides what the sidebar "Analisar app (RE)" action should do for a saved lab.
// Pure: no DOM, no network, no mutation. The caller executes the returned plan.
// RE is bound to the active lab (backend gates on lab_sessions.current), so a lab
// that is not current must be resumed before its APK can be extracted and analyzed.
(function (root) {
  function labReaPlan(lab, context) {
    const pkg = lab && lab.package_id ? String(lab.package_id) : '';
    if (!pkg) return { allowed: false, reason: 'Este lab não tem aplicativo para analisar.' };
    const isCurrent = !!context && lab.id === context.currentId;
    return { allowed: true, package: pkg, isCurrent, needsResume: !isCurrent };
  }
  const api = { labReaPlan };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.huntmobLabRea = api;
})(typeof window === 'undefined' ? this : window);
