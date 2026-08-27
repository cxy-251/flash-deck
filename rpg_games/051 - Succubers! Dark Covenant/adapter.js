// Adapter patch for 051 - Succubers! Dark Covenant
// Preloads Chinese translation JSON files and binds them to DKTools Localization & Window_Base

(function() {
    console.log("[Omni-Deck] Loading Succubers! Dark Covenant localization adapter...");

    var dict = {};
    var files = [
        'Actors_zh-CN.json', 'CharaName_zh-CN.json', 'Classes_zh-CN.json',
        'CommonEvents_C_zh-CN.json', 'CommonEvents_S_zh-CN.json', 'CommonEvents_zh-CN.json',
        'Enemies_zh-CN.json', 'Items_zh-CN.json', 'Map_C_zh-CN.json',
        'MapInfos_zh-CN.json', 'MapnameInMap_zh-CN.json', 'Map_S_zh-CN.json',
        'Map_zh-CN.json', 'menu_zh-CN.json', 'PlugIn_zh-CN.json',
        'RecollectionMode_zh-CN.json', 'Skills_zh-CN.json', 'States_zh-CN.json',
        'System_zh-CN.json', 'Troops_zh-CN.json'
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
    console.log("[Omni-Deck] Loaded", Object.keys(dict).length, "translation keys for zh-CN.");

    function replaceTags(text) {
        if (text === null || text === undefined) return text;
        var str = String(text);
        if (str.length < 2) return str;

        str = str.replace(/\{([^{}\s]+)\}/g, function(match, key) {
            if (dict.hasOwnProperty(key)) return dict[key];
            return match;
        });

        if (dict.hasOwnProperty(str)) {
            return dict[str];
        }

        return str;
    }

    var checkDK = setInterval(function() {
        if (typeof DKTools !== 'undefined' && DKTools.Localization) {
            DKTools.Localization._locale = 'zh-CN';
            if (!DKTools.Localization._data) DKTools.Localization._data = {};
            DKTools.Localization._data['zh-CN'] = dict;
            DKTools.Localization._languages = { 'zh-CN': 'Simplified Chinese', 'en': 'English' };
            DKTools.Localization._isReady = true;

            DKTools.Localization.initialize = async function() {
                this._locale = 'zh-CN';
                this._languages = { 'zh-CN': 'Simplified Chinese', 'en': 'English' };
                this._data = { 'zh-CN': dict, 'en': dict };
                this._isReady = true;
                return Promise.resolve();
            };
            DKTools.Localization.loadData = async function() {
                this._data = { 'zh-CN': dict, 'en': dict };
                this._isReady = true;
                return Promise.resolve();
            };
            DKTools.Localization.loadLocale = async function() {
                return 'zh-CN';
            };
        }
    }, 10);

    var hookText = setInterval(function() {
        if (typeof Window_Base !== 'undefined' && Window_Base.prototype.drawTextEx) {
            clearInterval(hookText);

            var origDrawTextEx = Window_Base.prototype.drawTextEx;
            Window_Base.prototype.drawTextEx = function(text, x, y, width) {
                return origDrawTextEx.call(this, replaceTags(text), x, y, width);
            };

            if (Window_Base.prototype.drawText) {
                var origDrawText = Window_Base.prototype.drawText;
                Window_Base.prototype.drawText = function(text, x, y, maxWidth, align) {
                    return origDrawText.call(this, replaceTags(text), x, y, maxWidth, align);
                };
            }
        }
    }, 30);
})();
