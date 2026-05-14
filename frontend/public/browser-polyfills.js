(function () {
  if (typeof Promise.withResolvers !== "function") {
    Promise.withResolvers = function withResolvers() {
      var resolve;
      var reject;
      var promise = new Promise(function (res, rej) {
        resolve = res;
        reject = rej;
      });
      return { promise: promise, resolve: resolve, reject: reject };
    };
  }
})();

