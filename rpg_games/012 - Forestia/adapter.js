// Adapter patch for 012 - Forestia
(function() {
    console.log("[Omni-Deck] Loading Forestia adapter patch...");

    var defaultGameEnv = { version: "1.0.6", build: "88c596a", lang: 2, trial: false };

    var checkIz = setInterval(function() {
        if (typeof Iz !== 'undefined') {
            if (Iz.Crypter) {
                Iz.Crypter.prototype.decrypt = function(encrypted) {
                    return JSON.stringify(defaultGameEnv);
                };
            }
            if (!Iz.Life) Iz.Life = {};
            if (!Iz.Life.env) Iz.Life.env = defaultGameEnv;

            if (!Iz.System) Iz.System = {};
            if (!Iz.System.isTestMode) Iz.System.isTestMode = function() { return false; };
            if (!Iz.System.isWebGLDebug) Iz.System.isWebGLDebug = function() { return false; };
        }
    }, 10);
})();
