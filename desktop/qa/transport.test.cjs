const { test } = require("node:test");
const assert = require("node:assert/strict");
const { Frames, encode } = require("../electron/transport.cjs");
test("split and concatenated unicode frames", () => {
  const seen = [];
  const parser = new Frames((m) => seen.push(m));
  const bytes = Buffer.concat([
    encode({ id: "1", result: "采集" }),
    encode({ id: "2", result: 20 }),
  ]);
  for (let i = 0; i < bytes.length; i += 3)
    parser.push(bytes.subarray(i, i + 3));
  assert.deepEqual(seen, [
    { id: "1", result: "采集" },
    { id: "2", result: 20 },
  ]);
});
test("reject oversize and stdout pollution", () => {
  assert.throws(() =>
    new Frames(() => {}).push(Buffer.from("Content-Length: 2097153\r\n\r\n")),
  );
  assert.throws(() =>
    new Frames(() => {}).push(Buffer.from("debug output\r\n\r\n")),
  );
  assert.throws(() => encode({ data: "x".repeat(2097152) }));
});

const {backendArgs}=require('../electron/launch-options.cjs');
const path=require('node:path'),fs=require('node:fs'),os=require('node:os');
test('launcher passes explicit adjacent configuration without cwd fallback',()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'Empire 配置 '));const file=path.join(folder,'config.toml');fs.writeFileSync(file,'# test template');
 try{assert.deepEqual(backendArgs(false,['app',`--empire-config=${file}`]),['-m','empire.desktop_bridge','--config',file]);assert.deepEqual(backendArgs(true,[`--empire-config=${file}`]),['--config',file]);assert.deepEqual(backendArgs(false,[]),['-m','empire.desktop_bridge']);assert.throws(()=>backendArgs(false,['--empire-config=relative.toml']));assert.throws(()=>backendArgs(false,[`--empire-config=${file}`,`--empire-config=${file}`]));}finally{fs.unlinkSync(file);fs.rmdirSync(folder);}
});
