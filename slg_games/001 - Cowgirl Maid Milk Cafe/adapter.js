// Adapter patch for 001 - Cowgirl Maid Milk Cafe
// Fixes DKTools localization data loading and ensures full Chinese text translation

(function() {
    console.log("[Omni-Deck] Loading Cowgirl Maid Milk Cafe localization adapter...");

    var dict = {};
    var files = [
        'Weapons_zh-CN.json', 'System_zh-CN.json', 'Command_zh-CN.json',
        'Map_zh-CN.json', 'plugins_zh-CN.json', 'Classes_zh-CN.json',
        'Items_zh-CN.json', 'menu_zh-CN.json', 'States_zh-CN.json',
        'Armors_zh-CN.json', 'CommonEvents_zh-CN.json', 'Enemies_zh-CN.json',
        'Skills_zh-CN.json', 'Actors_zh-CN.json', 'MapInfos_zh-CN.json',
        'CharaName_zh-CN.json'
    ];

    for (var i = 0; i < files.length; i++) {
        try {
            var xhr = new XMLHttpRequest();
            xhr.open('GET', 'locales/zh-CN/' + files[i] + '?t=' + Date.now(), false);
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

    window.LocaleDictionary = dict;
    console.log("[Omni-Deck] Successfully loaded", Object.keys(dict).length, "translation keys for zh-CN.");

    function replaceTags(text) {
        if (text === null || text === undefined) return text;
        var str = String(text);
        if (str.length < 3) return str;

        // 1. Replace {TAG} format (e.g. {SYS00001}, {ACT00001001}, {Command001})
        str = str.replace(/\{([^{}\s]+)\}/g, function(match, key) {
            if (dict.hasOwnProperty(key)) return dict[key];
            return match;
        });

        // 2. Direct replacement if exact bare match
        if (dict.hasOwnProperty(str)) {
            return dict[str];
        }

        return str;
    }

    function translateObject(obj, visited) {
        if (!obj || typeof obj !== 'object') return;
        if (!visited) visited = new Set();
        if (visited.has(obj)) return;
        visited.add(obj);

        for (var key in obj) {
            if (!obj.hasOwnProperty(key)) continue;
            var val = obj[key];
            if (typeof val === 'string') {
                if (val.indexOf('{') >= 0) {
                    obj[key] = replaceTags(val);
                } else if (dict.hasOwnProperty(val)) {
                    obj[key] = dict[val];
                }
            } else if (typeof val === 'object' && val !== null) {
                translateObject(val, visited);
            }
        }
    }

    // 1. Hook DKTools.Localization
    var hookDKInterval = setInterval(function() {
        if (window.DKTools && window.DKTools.Localization) {
            window.DKTools.Localization._data = dict;
            window.DKTools.Localization._locale = 'zh-CN';
            window.DKTools.Localization._isReady = true;

            var origGetText = window.DKTools.Localization.getText;
            window.DKTools.Localization.getText = function(text) {
                if (text === null || text === undefined) return text;
                return replaceTags(text);
            };

            var origLoadData = window.DKTools.Localization.loadData;
            window.DKTools.Localization.loadData = async function() {
                this._data = dict;
                this._locale = 'zh-CN';
                return dict;
            };
        }
    }, 20);

    // 2. Hook DataManager database loading
    var hookDataInterval = setInterval(function() {
        if (window.DataManager && !DataManager._deckLocalizationHooked) {
            DataManager._deckLocalizationHooked = true;
            clearInterval(hookDataInterval);

            var _orig_DataManager_isDatabaseLoaded = DataManager.isDatabaseLoaded;
            DataManager.isDatabaseLoaded = function() {
                var loaded = _orig_DataManager_isDatabaseLoaded.call(this);
                if (loaded && !this._deckTranslated) {
                    this._deckTranslated = true;
                    console.log("[Omni-Deck] Pre-translating database objects...");
                    var databases = [
                        window.$dataSystem, window.$dataActors, window.$dataClasses,
                        window.$dataSkills, window.$dataItems, window.$dataWeapons,
                        window.$dataArmors, window.$dataEnemies, window.$dataTroops,
                        window.$dataStates, window.$dataMapInfos, window.$dataCommonEvents
                    ];
                    var visited = new Set();
                    for (var i = 0; i < databases.length; i++) {
                        if (databases[i]) translateObject(databases[i], visited);
                    }
                    if (window.$dataSystem && window.$dataSystem.gameTitle) {
                        document.title = replaceTags(window.$dataSystem.gameTitle);
                    }
                    console.log("[Omni-Deck] Database pre-translation complete.");
                }
                return loaded;
            };

            var _orig_DataManager_onLoad = DataManager.onLoad;
            DataManager.onLoad = function(object) {
                _orig_DataManager_onLoad.call(this, object);
                if (object) {
                    translateObject(object);
                }
            };
        }
    }, 20);

    // 3. Hook Window and Bitmap text drawing
    var hookWindowInterval = setInterval(function() {
        if (window.Window_Base && !Window_Base.prototype._deckTextHooked) {
            Window_Base.prototype._deckTextHooked = true;
            clearInterval(hookWindowInterval);

            var _orig_Window_Base_drawText = Window_Base.prototype.drawText;
            Window_Base.prototype.drawText = function(text, x, y, maxWidth, align) {
                _orig_Window_Base_drawText.call(this, replaceTags(text), x, y, maxWidth, align);
            };

            var _orig_Window_Base_drawTextEx = Window_Base.prototype.drawTextEx;
            Window_Base.prototype.drawTextEx = function(text, x, y) {
                return _orig_Window_Base_drawTextEx.call(this, replaceTags(text), x, y);
            };

            var _orig_Window_Base_convertEscapeCharacters = Window_Base.prototype.convertEscapeCharacters;
            Window_Base.prototype.convertEscapeCharacters = function(text) {
                return _orig_Window_Base_convertEscapeCharacters.call(this, replaceTags(text));
            };
        }

        if (window.Bitmap && !Bitmap.prototype._deckTextHooked) {
            Bitmap.prototype._deckTextHooked = true;

            var _orig_Bitmap_drawText = Bitmap.prototype.drawText;
            Bitmap.prototype.drawText = function(text, x, y, maxWidth, lineHeight, align) {
                _orig_Bitmap_drawText.call(this, replaceTags(text), x, y, maxWidth, lineHeight, align);
            };
        }
    }, 20);

})();
