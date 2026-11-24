(() => {
  const site = {{ . | jsonify }};
  if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(site)) return;

  window.goatcounter = {
    path: window.location.pathname,
    title: "",
    referrer: "",
    no_session: true,
    no_events: true,
  };
  const script = document.createElement("script");
  script.async = true;
  script.referrerPolicy = "no-referrer";
  script.src = "https://gc.zgo.at/count.js";
  script.dataset.goatcounter = "https://" + site + ".goatcounter.com/count";
  document.head.append(script);
})();
