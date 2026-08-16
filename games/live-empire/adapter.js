// Live Empire (直播帝国) Specific Adapter Patch

(function() {
    console.log("[RPG-Deck] Loading live-empire adapter patches...");

    // 修复残留的 Axure 依赖
    window.$axure = {
        loadDocument: function() {}
    };
})();
