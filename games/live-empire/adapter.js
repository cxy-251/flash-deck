// Live Empire (直播帝国) Specific Adapter Patch

(function() {
    console.log("[RPG-Deck] Loading live-empire adapter patches...");

    // 1. 修复 Axure 原型脚本
    window.$axure = { loadDocument: function() {} };

    // 2. 模拟 DLC 全部已解锁已安装
    window.dlc_installed = function() { return true; };
    window.dlc_install = function() { return true; };

    // 3. 拦截 RoomInfoItem 防御空主播存档引发的 null.name 报错
    var checkRoomItemInterval = setInterval(function() {
        if (window.RoomInfoItem && window.RoomInfoItem.prototype) {
            clearInterval(checkRoomItemInterval);
            console.log("[RPG-Deck] Patching RoomInfoItem.prototype.dataChanged...");
            var origDataChanged = window.RoomInfoItem.prototype.dataChanged;
            window.RoomInfoItem.prototype.dataChanged = function() {
                if (this.data) {
                    if (this.data.status === 2 && !this.data.anchor) {
                        this.data.anchor = { id: "1", name: "主播", resid: "1", tl: 1, fans: 100, type: 1, xz: 0 };
                    }
                    if (this.data.status === 3 && !this.data.endDesc) {
                        this.data.endDesc = { name: "主播", type: 1, fs: 0, sy: 0, rq: 0, yz: 0, kc: 0, cy: 0 };
                    }
                }
                if (origDataChanged) {
                    try {
                        origDataChanged.apply(this, arguments);
                    } catch(err) {
                        console.warn("[RPG-Deck] Safe guarded RoomInfoItem dataChanged:", err);
                    }
                }
            };
        }
    }, 10);
})();
