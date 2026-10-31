import test from "node:test";
import assert from "node:assert/strict";
import { emptyLibrary, parseLibrary, makeEntry, loadLibrary, writeLibrary, mergeLibrary, markRead, readStatus, libraryMarkdown, referenceBatches, LIBRARY_KEY } from "../src/library.ts";
const ID="a".repeat(32),HASH="b".repeat(64),NEW_HASH="c".repeat(64);
const project={id:1,url:"https://github.com/owner/old-name",full_name:"owner/old-name",description:"Source description",summary_zh:"Should never survive a cached snapshot"};
const news={id:ID,url:"https://example.com/article",title:"A source announcement",summary:"Original source text",content_hash:HASH};
test("legacy favorites retain identity without fabricating their saved time",()=>{
  const state=parseLibrary(JSON.stringify([{type:"project",id:"1",data:project}]));
  assert.equal(state.entries[0].saved_at,null);
  assert.equal(state.entries[0].id,"1");
  assert.equal(state.entries[0].data.summary_zh,undefined);
});
test("unsupported or unsafe imports fail before storage changes",()=>{
  const storage={value:"untouched",getItem(){return this.value},setItem(_,value){this.value=value}};
  assert.throws(()=>parseLibrary(JSON.stringify({format:"github-rank-library",version:99,entries:[]})));
  assert.throws(()=>parseLibrary(JSON.stringify([{type:"news",id:ID,data:{...news,url:"javascript:alert(1)"}}])));
  assert.equal(storage.value,"untouched");
});
test("a single-key write failing leaves the previously stored library intact",()=>{
  const state=emptyLibrary();
  state.entries.push(makeEntry("project","1",project));
  const storage={getItem(){return "original"},setItem(){throw new Error("QuotaExceededError")}};
  assert.throws(()=>writeLibrary(storage,state));
  assert.equal(storage.getItem(LIBRARY_KEY),"original");
});
test("corrupt storage is surfaced and not automatically overwritten",()=>{
  let writes=0;
  const result=loadLibrary({getItem(){return "{bad"},setItem(){writes++}});
  assert.ok(result.error);
  assert.equal(result.raw,"{bad");
  assert.equal(writes,0);
});
test("import merges by type and id and preserves existing collection snapshots",()=>{
  const current=emptyLibrary(),incoming=emptyLibrary();
  current.entries.push(makeEntry("project","1",project,"2026-10-30T00:00:00Z"));
  incoming.entries.push(makeEntry("project","1",{...project,full_name:"owner/new-name"},"2026-10-31T00:00:00Z"));
  incoming.entries.push(makeEntry("news",ID,news));
  const merged=mergeLibrary(current,incoming);
  assert.equal(merged.entries.length,2);
  assert.equal(merged.entries[0].data.full_name,"owner/old-name");
  assert.equal(current.entries.length,1);
});
test("read marks are version-aware and importing older marks cannot replace newer ones",()=>{
  const state=markRead(emptyLibrary(),ID,HASH,"2026-10-31T00:00:00Z");
  assert.equal(readStatus(undefined,HASH),"unread");
  assert.equal(readStatus(state.reading[ID],HASH),"read");
  assert.equal(readStatus(state.reading[ID],NEW_HASH),"updated");
  const older=markRead(emptyLibrary(),ID,NEW_HASH,"2026-10-30T00:00:00Z");
  assert.equal(mergeLibrary(state,older).reading[ID].content_hash,HASH);
});
test("read retention is bounded and retains the newest mark",()=>{
  const state=emptyLibrary();
  for (let i=1;i<=5000;i++) state.reading[i.toString(16).padStart(32,"0")]={read_at:"2026-10-30T00:00:00.000Z",content_hash:null};
  const result=markRead(state,"f".repeat(32),HASH,"2026-10-31T00:00:00Z");
  assert.equal(Object.keys(result.reading).length,5000);
  assert.equal(result.reading["f".repeat(32)].content_hash,HASH);
});
test("backup round trip retains collection and reading state",()=>{
  const state=markRead(emptyLibrary(),ID,HASH);
  state.entries.push(makeEntry("news",ID,news));
  assert.deepEqual(parseLibrary(JSON.stringify(state)),state);
});
test("Markdown escapes source text and URL parentheses",()=>{
  const state=emptyLibrary();
  state.entries.push(makeEntry("news",ID,{...news,title:"A [source]",url:"https://example.com/a(b)"}));
  const output=libraryMarkdown(state);
  assert.ok(output.includes("\\[source\\]"));
  assert.ok(output.includes("a%28b%29"));
});
test("batch resolution stays within a short URL and the API reference budget",()=>{
  const state=emptyLibrary();
  for (let i=1;i<=201;i++) state.entries.push(makeEntry("news",i.toString(16).padStart(32,"0"),{...news,id:i.toString(16).padStart(32,"0")}));
  const batches=referenceBatches(state.entries);
  assert.equal(batches.length,3);
  assert.equal(new URL("http://localhost"+batches[2]).searchParams.get("news").split(",").length,1);
});
