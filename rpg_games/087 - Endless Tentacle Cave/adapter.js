// Adapter patch for 087 - Endless Tentacle Cave
(function() {
    console.log("[Omni-Deck] Loading Endless Tentacle Cave adapter...");

    function unwrapTags(text) {
        if (text === null || text === undefined) return text;
        var str = String(text);
        if (str.length < 2) return str;
        return str.replace(/\{([^{}\s]+)\}/g, function(match, key) {
            return key;
        });
    }

    var checkDK = setInterval(function() {
        if (typeof DKTools !== 'undefined' && DKTools.Localization) {
            clearInterval(checkDK);
            DKTools.Localization._isReady = true;
            DKTools.Localization._locale = 'ch';
            if (!DKTools.Localization._data) DKTools.Localization._data = {};
            DKTools.Localization.getText = function(text) {
                return unwrapTags(text);
            };
        }
    }, 20);

    var hookText = setInterval(function() {
        if (typeof Window_Base !== 'undefined' && Window_Base.prototype.drawTextEx) {
            clearInterval(hookText);
            var origDrawTextEx = Window_Base.prototype.drawTextEx;
            Window_Base.prototype.drawTextEx = function(text, x, y, width) {
                return origDrawTextEx.call(this, unwrapTags(text), x, y, width);
            };
            if (Window_Base.prototype.drawText) {
                var origDrawText = Window_Base.prototype.drawText;
                Window_Base.prototype.drawText = function(text, x, y, maxWidth, align) {
                    return origDrawText.call(this, unwrapTags(text), x, y, maxWidth, align);
                };
            }
        }
    }, 30);
})();
