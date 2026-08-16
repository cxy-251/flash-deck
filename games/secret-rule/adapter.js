// Secret Rule Specific Patches
(function() {
    console.log("[RPG-Deck] Loading secret-rule specific patches...");

    // Force default fonts to ensure visibility on Linux/SteamOS
    var fontInterval = setInterval(function() {
        if (window.Yanfly && window.Yanfly.Param) {
            clearInterval(fontInterval);
            // Replace Windows-specific fonts with universal sans-serif
            if (Yanfly.Param.MSGCNFontName) {
                Yanfly.Param.MSGCNFontName = '"Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif';
            }
            if (Yanfly.Param.MSGFontName) {
                Yanfly.Param.MSGFontName = '"Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif';
            }
        }
    }, 20);

    // Some texts might be transparent or missing due to control characters, 
    // we can add a fallback if Window_Message is available.
    var winMsgInterval = setInterval(function() {
        if (window.Window_Message) {
            clearInterval(winMsgInterval);
            var _Window_Message_startMessage = Window_Message.prototype.startMessage;
            Window_Message.prototype.startMessage = function() {
                _Window_Message_startMessage.call(this);
                // If message is somehow empty after translation, put a fallback
                if (this._textState && this._textState.text === "") {
                    this._textState.text = "......";
                }
            };
        }
    }, 20);
})();
