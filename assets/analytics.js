(() => {
  const websiteId = {{ . | jsonify }};
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(websiteId)) return;

  const campaignFields = new Set(["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]);
  window.filterSiteAnalytics = (_, payload) => {
    const page = new URL(payload.url, window.location.origin);
    for (const field of [...page.searchParams.keys()]) {
      if (!campaignFields.has(field)) page.searchParams.delete(field);
    }
    return {
      ...payload,
      url: page.pathname + page.search,
      referrer: payload.referrer ? new URL(payload.referrer, window.location.origin).origin : "",
    };
  };

  const script = document.createElement("script");
  script.async = true;
  script.referrerPolicy = "no-referrer";
  script.src = "https://cloud.umami.is/script.js";
  script.dataset.websiteId = websiteId;
  script.dataset.domains = "sunaybhat.me";
  script.dataset.doNotTrack = "true";
  script.dataset.excludeHash = "true";
  script.dataset.beforeSend = "filterSiteAnalytics";
  document.head.append(script);
})();
