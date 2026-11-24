(() => {
  const token = {{ . | jsonify }};
  if (!/^[a-f0-9]{32}$/i.test(token)) return;

  const script = document.createElement("script");
  script.type = "module";
  script.referrerPolicy = "no-referrer";
  script.src = "https://static.cloudflareinsights.com/beacon.min.js";
  script.dataset.cfBeacon = JSON.stringify({token, spa: false});
  document.head.append(script);
})();
