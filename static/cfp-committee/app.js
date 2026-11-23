"use strict";

const $ = id => document.getElementById(id);
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const money = new Intl.NumberFormat("en-US", {style:"currency", currency:"USD"});
const time = new Intl.DateTimeFormat("en-US", {month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZone:"America/Los_Angeles",timeZoneName:"short"});
const fmtTime = value => value ? time.format(new Date(value)) : "Pending";
const fmtNum = (x, digits = 2) => Number(x).toFixed(digits);
const modelNames = data => data.results.model_names;
const info = window.CFP_DATA;

if (!info) {
  $("official-state").textContent = "Dataset unavailable. Open the complete extracted dashboard folder.";
} else {
  const {results, ballots} = info;
  const {provenance: p, runs, condition_names: conditions, personas, analysis, sensitivity} = results;
  const models = modelNames(info);
  const committees = {
    "mixed|0.3":"Mixed panel · 0.3",
    "mixed|0.7":"Mixed panel · 0.7",
    ...Object.fromEntries(Object.entries(models).map(([id,name]) => [id+"|0.3",name])),
  };

  function options(node, rows, selected) {
    node.replaceChildren(...Object.entries(rows).map(([value,label]) => {
      const option = el("option", label);
      option.value = value;
      return option;
    }));
    if (selected && Object.hasOwn(rows, selected)) node.value = selected;
  }

  const snapshot = [
    ["Target release", p.release_id],
    ["Valid ballots", p.valid_ballots+" / "+p.requested_ballots],
    ["Qualified committees", Object.keys(runs).length+" / "+Object.keys(p.valid_by_group).length],
    ["Models", Object.keys(models).length],
    ["Reported model spend", money.format(p.cost_usd)],
  ];
  for (const [label,value] of snapshot) {
    const row = el("div");
    row.append(el("dt",label),el("dd",value));
    $("snapshot").append(row);
  }
  const locked = p.lock.status === "pushed";
  $("official-state").textContent = p.official_status === "available"
    ? "Official CFP comparison available"
    : (locked ? "Forecast locked · Official results pending" : "Forecast recorded · Official results pending");
  for (const sentence of [
    "Games considered through "+p.source.games_through+" in Eastern time.",
    "Packet frozen "+fmtTime(p.source.fetched_at_utc)+".",
    "Balloting "+fmtTime(p.started_at_utc)+" to "+fmtTime(p.finished_at_utc)+".",
    locked ? "GitHub lock verified "+fmtTime(p.lock.verified_at_utc)+"." : "GitHub timestamp proof pending.",
    "Target CFP release "+p.release_id+". Official comparison is added after release.",
  ]) $("timeline").append(el("li",sentence));
  if (locked) {
    const item = el("li");
    item.append("Lock tag ", el("code", p.lock.tag));
    $("timeline").append(item);
  }
  $("personas").className = "persona-list";
  for (const persona of Object.values(personas)) {
    const item = el("article");
    item.append(el("strong",persona.name+" · "+persona.seats+" seats"),el("p",persona.description));
    $("personas").append(item);
  }
  options($("committee"), committees, "mixed|0.3");
  options($("condition"),conditions,"cfp_on_ap_on");

  function selection() {
    const [model,temp] = $("committee").value.split("|");
    const condition = $("condition").value;
    return {key:[model,condition,temp].join("|"), condition};
  }

  function renderRationales(team, focus, filter = "") {
    const pane = $("rationale-panel");
    const {key} = selection();
    const rows = ballots.filter(b => b.group === key && b.rationales[team]);
    const heading = el("header");
    const close = el("button","Close","text-button");
    close.type = "button";
    close.addEventListener("click", () => {
      pane.hidden = true;
      const trigger = [...document.querySelectorAll(".team-button")].find(button => button.textContent === team);
      trigger?.focus();
    });
    heading.append(el("h3",team+" · Ballot justifications"),close);
    pane.replaceChildren(heading);
    const label = el("label","Persona");
    const select = el("select");
    options(select,{"":"All personas",...Object.fromEntries(Object.entries(personas).map(([id,p]) => [id,p.name]))},filter);
    label.append(select);
    const controls = el("div",undefined,"rationale-controls");
    controls.append(label,el("p",rows.length+" top-12 ballot votes"));
    pane.append(controls);
    const list = el("div");
    const show = () => {
      const displayed = rows.filter(b => !select.value || b.persona === select.value);
      list.replaceChildren(...displayed.map(b => {
        const item = el("article");
        item.append(el("small",b.agent_id+" · "+models[b.model]+" · "+personas[b.persona].name+
          " · rank "+(b.ranking.indexOf(team)+1)),el("p",b.rationales[team]));
        return item;
      }));
      if (!displayed.length) list.append(el("p","No justifications match this team and persona.","unavailable"));
    };
    select.addEventListener("change",show);
    pane.append(list);
    pane.hidden = false;
    show();
    if (focus) pane.focus();
  }

  function emptyRow(node, message) {
    const row = el("tr");
    const cell = el("td",message);
    cell.colSpan = 4;
    row.append(cell);
    node.append(row);
  }

  function renderRankings() {
    const {key} = selection();
    const run = runs[key];
    const top = $("ranking-rows");
    const rest = $("ranking-extra");
    const query = $("team-filter").value.trim().toLowerCase();
    top.replaceChildren(); rest.replaceChildren();
    const subset = ballots.filter(b => b.group === key);
    $("selection-note").textContent = (p.valid_by_group[key] ?? 0) +
      " of 13 ballots valid · "+conditions[selection().condition];
    $("rank-more").hidden = !run || !!query;
    if (!run) {
      emptyRow(top,"This group did not meet the 10-ballot threshold.");
      return;
    }
    run.ranking.forEach((team, index) => {
      if (query && !team.toLowerCase().includes(query)) return;
      const row = el("tr");
      const button = el("button",team,"team-button");
      button.type = "button";
      button.addEventListener("click",() => renderRationales(team,true));
      const teamCell = el("td");
      teamCell.append(button);
      const votes = subset.filter(b => b.ranking.slice(0,12).includes(team)).length;
      row.append(el("td",index+1,"rank-num"),teamCell,el("td",run.points[team]),el("td",votes+" / "+subset.length));
      (query || index<12 ? top : rest).append(row);
    });
    if (!top.children.length) emptyRow(top,"No ranked teams match your search.");
  }

  function matrix(target, rows, cols, title, cell) {
    const container = el("div",undefined,"matrix-scroll");
    const table = el("table",undefined,"matrix");
    table.append(el("caption",title,"sr-only"));
    const header = el("tr");
    header.append(el("th",""));
    for (const [,name] of cols) {
      const th=el("th",name); th.scope="col"; header.append(th);
    }
    const thead=el("thead");thead.append(header);
    table.append(thead);
    const body=el("tbody"); table.append(body);
    for (const [row,name] of rows) {
      const tr = el("tr");
      const th=el("th",name,"row-name"); th.scope="row"; tr.append(th);
      for (const [col] of cols) {
        const value=cell(row,col);
        const td=el("td",value ? value.text : "—",value ? undefined : "na");
        if (value) {
          td.title=value.title || value.text;
          td.style.background=value.fill || "#eef4ee";
        }
        tr.append(td);
      }
      body.append(tr);
    }
    container.append(table);
    $(target).replaceChildren(container);
  }

  function shade(x, warm = false) {
    return warm ? "hsl(31 74% "+(96-23*Math.min(Math.abs(x),1))+"%)" :
      "hsl(154 42% "+(97-27*Math.min(Math.abs(x),1))+"%)";
  }

  function bars(target, items, max) {
    const list=el("div",undefined,"bar-list");
    for (const item of items) {
      const row=el("div",undefined,"bar-row");
      const track=el("div",undefined,"bar-track");
      track.setAttribute("aria-hidden","true");
      const fill=el("i");
      fill.style.width=Math.max(0,Math.min(item.value/max*100,100))+"%";
      if(item.color) fill.style.background=item.color;
      track.append(fill);
      row.append(el("span",item.label),track,el("span",item.text,"bar-value"));
      if(item.title) row.title=item.title;
      list.append(row);
    }
    $(target).replaceChildren(items.length ? list : el("p","No qualifying comparison is available.","unavailable"));
  }

  function renderCharts() {
    const condition=$("condition").value;
    const a=analysis[condition];
    const available=a.models.map(model=>[model,models[model]]);
    const metric=$("agreement-metric").value;
    const fraction=metric==="overlap";
    matrix("model-chart",available,available,"Solo committee agreement", (left,right)=>{
      const value=left===right ? (fraction?12:1) :
        (a.agreement[left+"|"+right] || a.agreement[right+"|"+left])?.[metric];
      if(value===undefined) return null;
      return {text:fraction?value+"/12":fmtNum(value),fill:shade(fraction?(value-7)/5:(value-.5)*2)};
    });
    matrix("persona-chart",Object.entries(personas).map(([id,p])=>[id,p.name]),available,
      "Mean absolute rank shift by persona and model",(persona,model)=>{
        const value=a.persona_distance[persona+"|"+model];
        if(!value) return null;
        return {text:fmtNum(value.distance,1),title:value.n+" persona ballots and "+value.others+" comparison ballots",
          fill:shade(value.distance/5)};
    });
    $("persona-chart").append(el("p","Higher values indicate more distinct placements. Hover for ballot counts.","chart-detail"));
    const shifts=Object.entries(models).flatMap(([id,name])=>["ap","cfp"].filter(poll=>sensitivity[id]?.[poll]).map(poll=>{
      const s=sensitivity[id][poll];
      return {label:name+" · "+(poll==="ap"?"AP":"CFP"),value:s.distance,text:fmtNum(s.distance,3),
        color:poll==="ap"?"#488974":"#99703b",title:s.n+" matched ballot pairs"};
    }));
    bars("sensitivity-chart",shifts,Math.max(.2,...shifts.map(x=>x.value)));
    bars("consensus-chart",a.consensus.slice(0,12).map(team=>({
      label:team.team,value:team.count,text:team.count+"/"+available.length,
    })),available.length||1);
    matrix("reference-chart",available,[["0.3","Mixed · 0.3"],["0.7","Mixed · 0.7"]],"Agreement with the mixed committee",(model,temp)=>{
      const s=a.mixed_agreement[model]?.[temp];
      return s ? {text:fmtNum(s.tau),fill:shade(s.tau),title:"Spearman "+fmtNum(s.rho)+" · Top-12 overlap "+s.overlap+"/12"} : null;
    });
    $("reference-chart").append(el("p","Target-release accuracy is pending the official rankings.","chart-detail"));
    matrix("validation-chart",Object.entries(models),Object.entries(conditions),"Ballot validity by condition",(model,c)=>{
      const value=p.valid_by_group[model+"|"+c+"|0.3"];
      return value===undefined ? null : {text:value+"/13",fill:shade(value/13,value<10)};
    });
  }

  function refresh() {
    $("rationale-panel").hidden=true;
    renderRankings();
    renderCharts();
  }
  $("committee").addEventListener("change",refresh);
  $("condition").addEventListener("change",refresh);
  $("team-filter").addEventListener("input",renderRankings);
  $("agreement-metric").addEventListener("change",renderCharts);
  refresh();
}
