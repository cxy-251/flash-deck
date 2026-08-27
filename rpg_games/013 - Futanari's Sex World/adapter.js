// Adapter patch for 013 - Futanari's Sex World
(function() {
    console.log("[Omni-Deck] Loading Futanari's Sex World localization adapter...");

    var pathMock = (typeof window.require !== 'undefined') ? window.require('path') : {
        normalize: function(p) { return p; },
        join: function() { return Array.from(arguments).join('/'); },
        dirname: function(p) { return p.substring(0, p.lastIndexOf('/')); },
        basename: function(p) { return p.substring(p.lastIndexOf('/') + 1); },
        extname: function(p) { var idx = p.lastIndexOf('.'); return idx >= 0 ? p.substring(idx) : ''; },
        resolve: function() { return Array.from(arguments).join('/'); },
        isAbsolute: function(p) { return p.startsWith('/') || /^[a-zA-Z]:/.test(p); }
    };

    var checkIO = setInterval(function() {
        if (typeof DKTools !== 'undefined') {
            if (DKTools.IO) {
                if (!DKTools.IO._path) {
                    try { DKTools.IO.initialize(); } catch(e) {}
                    if (!DKTools.IO._path) DKTools.IO._path = pathMock;
                }
            }
            if (DKTools.Utils && !DKTools.Utils._isReady) {
                try { DKTools.Utils.initialize(); } catch(e) {}
            }
            if (DKTools.StartupManager) {
                DKTools.StartupManager._isReady = true;
            }
        }
    }, 2);

    var localesData = { 'ch': {}, 'en': {} };

    function loadJson(url) {
        try {
            var xhr = new XMLHttpRequest();
            xhr.open('GET', url + '?t=' + Date.now(), false);
            xhr.send();
            if (xhr.status === 200) {
                return JSON.parse(xhr.responseText);
            }
        } catch(e) {
            console.error('[Omni-Deck] Failed to load ' + url + ':', e);
        }
        return {};
    }

    localesData['ch'] = loadJson('locales/ch.json');
    localesData['en'] = loadJson('locales/en.json');

    var currentLocale = 'ch';
    var activeDict = localesData['ch'];

    window.LocaleDictionary = activeDict;
    console.log("[Omni-Deck] Loaded", Object.keys(activeDict).length, "translation keys for ch.");

    function setLocale(loc) {
        if (localesData[loc] && Object.keys(localesData[loc]).length > 0) {
            currentLocale = loc;
            activeDict = localesData[loc];
            window.LocaleDictionary = activeDict;
        }
        if (typeof DKTools !== 'undefined' && DKTools.Localization) {
            DKTools.Localization._locale = currentLocale;
            DKTools.Localization._data = activeDict;
            DKTools.Localization._cache = {};
            DKTools.Localization._cacheVariables = {};
        }
    }

    function replaceTags(text) {
        if (text === null || text === undefined) return text;
        var str = String(text);
        if (str.length < 2) return str;

        // Match {anything} except nested braces and newlines
        str = str.replace(/\{([^\{\}\r\n]+)\}/g, function(match, rawKey) {
            var key = rawKey.trim();
            if (activeDict.hasOwnProperty(key)) return activeDict[key];
            if (activeDict.hasOwnProperty(rawKey)) return activeDict[rawKey];
            var keyLow = key.toLowerCase();
            for (var k in activeDict) {
                if (k.toLowerCase() === keyLow) return activeDict[k];
            }
            return match;
        });

        var trimmed = str.trim();
        if (activeDict.hasOwnProperty(trimmed)) {
            return activeDict[trimmed];
        }
        if (activeDict.hasOwnProperty(str)) {
            return activeDict[str];
        }
        var strLow = trimmed.toLowerCase();
        for (var k in activeDict) {
            if (k.toLowerCase() === strLow) return activeDict[k];
        }

        return str;
    }

    var checkDK = setInterval(function() {
        if (typeof DKTools !== 'undefined' && DKTools.Localization) {
            DKTools.Localization._locale = currentLocale;
            DKTools.Localization._data = activeDict;
            DKTools.Localization._languages = { 'ch': '中文', 'en': 'English' };
            if (!DKTools.Localization._cache) DKTools.Localization._cache = {};
            if (!DKTools.Localization._cacheVariables) DKTools.Localization._cacheVariables = {};
            if (!DKTools.Localization._folders) DKTools.Localization._folders = {};
            DKTools.Localization._isReady = true;

            DKTools.Localization.initialize = async function() {
                this._locale = currentLocale;
                this._languages = { 'ch': '中文', 'en': 'English' };
                this._data = activeDict;
                this._cache = {};
                this._cacheVariables = {};
                this._folders = {};
                this._isReady = true;
                return Promise.resolve();
            };
            DKTools.Localization.loadData = async function() {
                this._data = activeDict;
                if (!this._cache) this._cache = {};
                if (!this._cacheVariables) this._cacheVariables = {};
                if (!this._folders) this._folders = {};
                this._isReady = true;
                return Promise.resolve();
            };
            DKTools.Localization.loadLocale = async function() {
                return currentLocale;
            };
            DKTools.Localization.selectLocale = async function(locale) {
                setLocale(locale);
                return Promise.resolve();
            };
            DKTools.Localization.getText = function(text, locale) {
                if (text == null) return text;
                var str = String(text);
                if (str.length < 1) return str;
                if (!this._cache) this._cache = {};
                if (!this._cacheVariables) this._cacheVariables = {};
                if (this._cache[str]) return this._cache[str].text;
                var res = replaceTags(str);
                this._cache[str] = { text: res };
                return res;
            };
            DKTools.Localization.isLocaleFileExists = function() {
                return true;
            };
            DKTools.Localization.isReady = function() {
                return true;
            };
            DKTools.Localization.getImageFolder = function(folder) {
                return folder;
            };
        }
    }, 5);

    var hookText = setInterval(function() {
        if (typeof Window_Base !== 'undefined' && Window_Base.prototype.convertEscapeCharacters) {
            clearInterval(hookText);

            var origConvertEscapeCharacters = Window_Base.prototype.convertEscapeCharacters;
            Window_Base.prototype.convertEscapeCharacters = function(text) {
                var translated = replaceTags(text);
                return origConvertEscapeCharacters.call(this, translated);
            };

            if (Window_Base.prototype.drawText) {
                var origDrawText = Window_Base.prototype.drawText;
                Window_Base.prototype.drawText = function(text, x, y, maxWidth, align) {
                    if (text == null) return origDrawText.call(this, text, x, y, maxWidth, align);
                    var str = replaceTags(text);
                    if (str.indexOf('\n') !== -1) str = str.split('\n')[0];
                    return origDrawText.call(this, str, x, y, maxWidth, align);
                };
            }

            if (typeof Bitmap !== 'undefined' && Bitmap.prototype.drawText) {
                var origBitmapDrawText = Bitmap.prototype.drawText;
                Bitmap.prototype.drawText = function(text, x, y, maxWidth, lineHeight, align) {
                    if (text == null) return origBitmapDrawText.call(this, text, x, y, maxWidth, lineHeight, align);
                    var str = replaceTags(text);
                    if (str.indexOf('\n') !== -1) str = str.split('\n')[0];
                    return origBitmapDrawText.call(this, str, x, y, maxWidth, lineHeight, align);
                };
            }
        }
    }, 10);
})();
