const path = require('node:path');
const fs = require('node:fs');

function backendArgs(packaged, argv) {
  const args = packaged ? [] : ['-m', 'empire.desktop_bridge'];
  const options = argv.filter(value => value.startsWith('--empire-config='));
  if (options.length > 1) throw Error('只能指定一个程序配置文件');
  if (options.length) {
    const file = options[0].slice('--empire-config='.length);
    if (!path.isAbsolute(file) || !fs.statSync(file).isFile())
      throw Error('程序配置必须为已存在文件的绝对路径');
    args.push('--config', file);
  }
  return args;
}
module.exports = { backendArgs };
