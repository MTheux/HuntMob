// AUTHORIZED TESTING ONLY — app selected in the owned HuntMob lab.
// Observe metadata; preserve original arguments, exceptions and return values.
const selected = __SCRIPTS__;
const limits = {};
function emit(script, kind, fields) {
  limits[script] = (limits[script] || 0) + 1;
  if (limits[script] > 500) return;
  send(Object.assign({script: script, kind: kind}, fields || {}));
}
function hook(script, name, method, describe) {
  try {
    const cls = Java.use(name);
    let count = 0;
    cls[method].overloads.forEach(function (overload) {
      overload.implementation = function () {
        const args = Array.prototype.slice.call(arguments);
        let fields = {};
        try { fields = describe ? describe.call(this, args) : {}; } catch (_) {}
        emit(script, 'call', Object.assign({class_name: name, method: method}, fields));
        return overload.apply(this, args);
      };
      count++;
    });
    emit(script, 'hook_ready', {class_name: name, method: method, overloads: count});
  } catch (_) { emit(script, 'hook_unavailable', {class_name: name, method: method}); }
}
Java.perform(function () {
  if (selected.includes('webview-observe')) {
    hook('webview-observe', 'android.webkit.WebView', 'loadUrl', function (args) {
      const uri = Java.use('android.net.Uri').parse(String(args[0]));
      return {scheme: String(uri.getScheme() || ''), hostname: String(uri.getHost() || '')};
    });
    hook('webview-observe', 'android.webkit.WebView', 'addJavascriptInterface');
  }
  if (selected.includes('crypto-observe')) {
    ['javax.crypto.Cipher', 'java.security.MessageDigest', 'javax.crypto.Mac'].forEach(function (name) {
      hook('crypto-observe', name, 'getInstance', function (args) {
        const algorithm = String(args[0]);
        return {algorithm: /^(AES|RSA|DES|DESede|ChaCha20|SHA-?[0-9]+|MD5|HmacSHA[0-9]+)(\/[A-Za-z0-9-]+){0,2}$/.test(algorithm) ? algorithm : '[OMITTED]'};
      });
    });
    hook('crypto-observe', 'javax.crypto.Cipher', 'init');
    hook('crypto-observe', 'javax.crypto.Cipher', 'doFinal');
  }
  if (selected.includes('file-observe')) {
    ['java.io.FileInputStream', 'java.io.FileOutputStream'].forEach(function (name) {
      hook('file-observe', name, '$init');
    });
    hook('file-observe', 'android.app.ContextImpl', 'openFileInput');
    hook('file-observe', 'android.app.ContextImpl', 'openFileOutput');
  }
  if (selected.includes('root-detection-observe')) {
    hook('root-detection-observe', 'java.io.File', 'exists', function () {
      const filename = String(this.getName());
      return {integrity_indicator: ['su', 'busybox', 'magisk', 'Superuser.apk'].includes(filename) ? filename : 'other_file'};
    });
  }
  if (selected.includes('biometric-monitor')) {
    ['android.hardware.biometrics.BiometricPrompt', 'android.hardware.fingerprint.FingerprintManager'].forEach(function (name) {
      hook('biometric-monitor', name, 'authenticate');
    });
  }
  if (selected.includes('tls-observe')) {
    hook('tls-observe', 'javax.net.ssl.SSLContext', 'init');
    hook('tls-observe', 'com.android.org.conscrypt.TrustManagerImpl', 'checkServerTrusted');
    hook('tls-observe', 'okhttp3.CertificatePinner', 'check');
  }
  send({kind: 'agent_ready', scripts: selected, java_available: Java.available});
});
