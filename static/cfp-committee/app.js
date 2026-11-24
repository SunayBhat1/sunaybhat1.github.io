"use strict";

const $ = id => document.getElementById(id);
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const releaseDate = new Intl.DateTimeFormat("en-US", {month:"long",day:"numeric",timeZone:"UTC"});
const time = new Intl.DateTimeFormat("en-US", {month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZone:"America/Los_Angeles",timeZoneName:"short"});
const fmtTime = value => value ? time.format(new Date(value)) : "Pending";
const fmtNum = (x, digits = 2) => Number(x).toFixed(digits);
const modelNames = data => data.results.model_names;
const info = window.CFP_DATA;

$("copy-prompt").addEventListener("click", async () => {
  const prompt = $("starter-prompt");
  const button = $("copy-prompt");
  try {
    await navigator.clipboard.writeText(prompt.textContent.trim());
    button.textContent = "Copied";
    $("copy-status").textContent = "Starter prompt copied.";
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(prompt);
    selection.removeAllRanges();
    selection.addRange(range);
    prompt.focus();
    $("copy-status").textContent = "Prompt selected for copying.";
  }
});

if (!info) {
  $("official-state").textContent = "Dataset unavailable. Open the complete extracted dashboard folder.";
} else {
  const {results, ballots} = info;
  const {provenance: p, runs, condition_names: conditions, personas, analysis, sensitivity} = results;
  const models = modelNames(info);
  const seats = Object.values(personas).reduce((total, persona) => total + persona.seats, 0);
  const committees = {
    "mixed|0.3":"Combined committee",
    "mixed|0.7":"Combined committee · second vote",
    ...Object.fromEntries(Object.entries(models).map(([id,name]) => [id+"|0.3",name])),
  };
  const committeeDescription = {
    "mixed|0.3": "The combined committee assigns different AI models to fixed seats with different voting styles.",
    "mixed|0.7": "The same mixed committee votes again. Models that support a creativity setting use a higher setting.",
  };

  const defaultGroup = "mixed|cfp_on_ap_on|0.3";
  $("release-label").textContent = "CFP forecast · " + releaseDate.format(new Date(p.release_id + "T12:00:00Z"));
  $("headline-team").textContent = runs[defaultGroup]?.ranking[0] ?? "—";
  const gamesThrough = releaseDate.format(new Date(p.source.games_through + "T12:00:00Z"));
  const recordNote = p.source.record_scope === "all_games"
    ? "Overall records include games against non-FBS opponents."
    : "Records in the ballots count FBS opponents only.";
  $("evidence-note").textContent = "Games through " + gamesThrough + ". " + recordNote;
  $("record-scope").textContent = recordNote;
  if (p.release_id === "2026-11-24" && p.source.ap_week === 12) {
    $("evidence-note").append(" The AP poll shown predates the Nov. 21 games.");
  }
  for (const [id, path, format] of [
    ["skill-size","SKILL.md","MD"],["results-size","data/results.json","JSON"],
  ]) {
    const bytes = info.download_sizes?.[path];
    if (bytes) {
      const size = bytes >= 1000000 ? fmtNum(bytes / 1000000, 2) + " MB" : fmtNum(bytes / 1000, 1) + " KB";
      $(id).textContent = format + " · " + size;
    }
  }
  if (results.roster_comparison) {
    const comparison = results.roster_comparison.groups[defaultGroup];
    const note = $("roster-note");
    note.append(el("strong","What changed with Head-to-Head First"));
    if (comparison?.top_12_in.length) {
      note.append(el("p",comparison.top_12_in.join(", ") + " moved into the combined committee’s top 12. " +
        comparison.top_12_out.join(", ") + " moved out."));
    } else if (comparison) {
      note.append(el("p","The combined committee picked the same 12 playoff teams in both runs with both polls shown."));
    }
    const details = el("details");
    details.append(el("summary","How we compared the two runs"));
    details.append(el("p","The rerun gave two of 13 seats to a voting style that favors head-to-head winners when résumés are close. All the models voted again, so differences also include normal variation between votes."));
    const close = results.roster_comparison.winner_preference.comparable_matchups;
    if (close?.changed_seats.new != null) {
      const percent = share => Math.round(100 * share) + "%";
      details.append(el("p", "Across " + close.unique_matchups + " matchups between teams with similar résumés, those two seats’ head-to-head winner score rose from " + percent(close.changed_seats.old) + " to " + percent(close.changed_seats.new) + ". The score counts ties as half."));
    }
    note.append(details);
    note.hidden = false;
  }

  function options(node, rows, selected) {
    node.replaceChildren(...Object.entries(rows).map(([value,label]) => {
      const option = el("option", label);
      option.value = value;
      return option;
    }));
    if (selected && Object.hasOwn(rows, selected)) node.value = selected;
  }

  const snapshot = [
    ["AI models", Object.keys(models).length],
    ["Ballots counted", p.valid_ballots],
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
    const link = el(p.lock.url ? "a" : "code",p.lock.tag);
    if (p.lock.url) link.href = p.lock.url;
    const item = el("li");
    item.append("Lock tag ",link);
    $("timeline").append(item);
  }
  $("personas").className = "persona-list";
  for (const [id, persona] of Object.entries(personas)) {
    const item = el("article");
    item.append(el("strong",persona.name+" · "+persona.seats+" seats"),el("p",persona.description));
    const prompts = Object.entries(p.system_prompts ?? {}).filter(([, prompt]) =>
      prompt.match(/; your persona is (\w+)\./)?.[1] === id
    );
    if (prompts.length) {
      const disclosure = el("details");
      disclosure.append(el("summary","Full system prompt"));
      const content = el("pre",prompts[0][1],"persona-prompt");
      if (prompts.length > 1) {
        const label = el("label","Voting seat");
        const select = el("select");
        options(select,Object.fromEntries(prompts.map(([seat]) => [seat,seat])));
        select.addEventListener("change", () => {
          content.textContent = prompts.find(([seat]) => seat === select.value)[1];
        });
        label.append(select);
        disclosure.append(label);
      }
      disclosure.append(content);
      item.append(disclosure);
    }
    $("personas").append(item);
  }
  const availableCommittees = new Set(Object.keys(p.valid_by_group).map(group => {
    const [model,,temp] = group.split("|");
    return model+"|"+temp;
  }));
  options($("committee"),Object.fromEntries(Object.entries(committees)
    .filter(([key]) => availableCommittees.has(key))),"mixed|0.3");
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
    cell.colSpan = 3;
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
      " of "+seats+" ballots valid · "+conditions[selection().condition];
    $("committee-description").textContent = committeeDescription[$("committee").value] ??
      "Every voter uses " + committees[$("committee").value] + " with a seat-specific voting style.";
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
      row.append(el("td",index+1,"rank-num"),teamCell,el("td",votes+" / "+subset.length));
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
          if (value.ink) td.style.color=value.ink;
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

  function agreementScale(values, format) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const ramp = ["#edf5ed", "#c7e6d8", "#8fc9b4", "#337765", "#18483b"];
    return {
      style(value) {
        if (max === min) return {fill:ramp[2]};
        const band = Math.min(ramp.length - 1, Math.floor((value-min)/(max-min)*ramp.length));
        return {fill:ramp[band], ink:band >= 3 ? "#fff" : "#132820"};
      },
      show(target) {
        if (!values.length) return;
        const legend = el("div",undefined,"color-legend");
        const track = el("div",undefined,"color-track");
        track.setAttribute("aria-hidden","true");
        for (const color of max === min ? [ramp[2]] : ramp) {
          const step = el("span");
          step.style.backgroundColor = color;
          track.append(step);
        }
        legend.append(el("span","Color scale across poll settings"),track,
          el("span",max === min ? format(min) : format(min)+" to "+format(max),"color-range"));
        $(target).append(legend);
      },
    };
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
    const formatAgreement = value => fraction ? value+"/12" : fmtNum(value);
    const modelScale = agreementScale(
      Object.values(analysis).flatMap(report=>Object.values(report.agreement).map(pair=>pair[metric])),
      formatAgreement
    );
    matrix("model-chart",available,available,"Solo committee agreement", (left,right)=>{
      if (left===right) return null;
      const value=(a.agreement[left+"|"+right] || a.agreement[right+"|"+left])?.[metric];
      if(value===undefined) return null;
      return {text:formatAgreement(value),...modelScale.style(value)};
    });
    modelScale.show("model-chart");
    $("model-chart").closest("article").hidden = available.length < 2;
    const conferences=a.conferences.map(conference=>[conference,conference]);
    matrix("persona-chart",Object.entries(personas).map(([id,p])=>[id,p.name]),conferences,
      "Mean rank gain by persona and conference",(persona,conf)=>{
        const edge=a.tilt[persona+"|"+conf];
        if(!edge) return null;
        return {text:(edge.delta>0?"+":"")+fmtNum(edge.delta,1),title:edge.n+" team–model comparisons",
          fill:shade(edge.delta/4,edge.delta<0)};
    });
    $("persona-chart").append(el("p","Green = higher placements. Amber = lower placements. Hover for sample size.","chart-detail"));
    $("persona-chart").closest("article").hidden = !Object.keys(a.tilt).length;
    const shifts=Object.entries(models).flatMap(([id,name])=>["ap","cfp"].filter(poll=>sensitivity[id]?.[poll]).map(poll=>{
      const s=sensitivity[id][poll];
      return {label:name+" · "+(poll==="ap"?"AP":"CFP"),value:s.distance,text:fmtNum(s.distance,3),
        color:poll==="ap"?"#488974":"#99703b",title:s.n+" matched ballot pairs"};
    }));
    bars("sensitivity-chart",shifts,Math.max(.2,...shifts.map(x=>x.value)));
    $("sensitivity-chart").closest("article").hidden = !shifts.length;
    bars("consensus-chart",a.consensus.slice(0,12).map(team=>({
      label:team.team,value:team.count,text:team.count+"/"+available.length,
    })),available.length||1);
    $("consensus-chart").closest("article").hidden = !available.length;
    const refs=[...new Set(Object.values(a.reference_scores).flatMap(Object.keys))];
    const referenceRows=Object.keys(a.reference_scores).map(id=>[id,models[id] ?? committees[id]]);
    const referenceScale = agreementScale(Object.values(analysis).flatMap(report=>
      Object.values(report.reference_scores).flatMap(scores=>Object.values(scores).map(score=>score.kendall_tau_b))
    ),fmtNum);
    matrix("reference-chart",referenceRows,refs.map(name=>[name,name+" · τ-b"]),"Agreement with reference polls",(model,ref)=>{
      const s=a.reference_scores[model][ref];
      return s ? {text:fmtNum(s.kendall_tau_b),...referenceScale.style(s.kendall_tau_b),title:"Spearman "+fmtNum(s.spearman)+" · Top-12 overlap "+s.top_12_overlap} : null;
    });
    referenceScale.show("reference-chart");
    if(p.official_status!=="available") $("reference-chart").append(el("p","Target-release accuracy is pending the official rankings.","chart-detail"));
    const validationRows=Object.entries(committees).filter(([id])=>availableCommittees.has(id));
    matrix("validation-chart",validationRows,Object.entries(conditions),"Ballot validity by condition",(committee,c)=>{
      const [model,temp]=committee.split("|");
      const value=p.valid_by_group[model+"|"+c+"|"+temp];
      return value===undefined ? null : {text:value+"/"+seats,fill:shade(value/seats,value<10)};
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
