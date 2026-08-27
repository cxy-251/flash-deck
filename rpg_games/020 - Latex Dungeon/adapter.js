// Adapter patch for 020 - Latex Dungeon
// Preloads Chinese translation JSON files and binds them to DKTools Localization & Window_Base

(function() {
    console.log("[Omni-Deck] Loading Latex Dungeon localization adapter...");

    var dict = {};
    var files = [
        'Enemy - Alien.json', 'Enemy - Demon.json', 'Enemy - Forest.json',
        'Enemy - Latex.json', 'Enemy - Slime.json', 'Enemy - Tentacles.json',
        'Main  - item.json', 'Main  - Main.json', 'Main  - Names.json',
        'Main  - Skill.json', 'Main  - system.json', 'Map - Alien.json',
        'Map - Demon.json', 'Map - END.json', 'Map - Forest.json',
        'Map - Latex.json', 'Map - opening-raid.json', 'Map - Slime.json',
        'Map - Tentacles.json', 'Map - Town.json'
    ];

    for (var i = 0; i < files.length; i++) {
        try {
            var xhr = new XMLHttpRequest();
            xhr.open('GET', 'locales/tw/' + encodeURIComponent(files[i]) + '?t=' + Date.now(), false);
            xhr.send();
            if (xhr.status === 200) {
                var json = JSON.parse(xhr.responseText);
                if (json && typeof json === 'object') {
                    for (var k in json) {
                        if (json.hasOwnProperty(k)) {
                            dict[k] = json[k];
                        }
                    }
                }
            }
        } catch(e) {
            console.error('[Omni-Deck] Failed to load locale file:', files[i], e);
        }
    }

    var currentLocale = 'tw';
    var activeDict = dict;

    window.LocaleDictionary = activeDict;
    console.log("[Omni-Deck] Loaded", Object.keys(activeDict).length, "translation keys for tw.");

    function setLocale(loc) {
        currentLocale = loc;
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
            DKTools.Localization._languages = { 'tw': '繁體中文', 'en': 'English' };
            if (!DKTools.Localization._cache) DKTools.Localization._cache = {};
            if (!DKTools.Localization._cacheVariables) DKTools.Localization._cacheVariables = {};
            if (!DKTools.Localization._folders) DKTools.Localization._folders = {};
            DKTools.Localization._isReady = true;

            DKTools.Localization.initialize = async function() {
                this._locale = currentLocale;
                this._languages = { 'tw': '繁體中文', 'en': 'English' };
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
