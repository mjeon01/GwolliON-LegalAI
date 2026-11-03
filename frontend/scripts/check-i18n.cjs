const fs = require('node:fs');
const path = require('node:path');
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;
const root = path.resolve(__dirname,'../src');
const messages = JSON.parse(fs.readFileSync(path.join(root,'i18n/messages.json'),'utf8'));
const failures = [];
function scan(folder) {
  for(const entry of fs.readdirSync(folder,{withFileTypes:true})) {
    const file = path.join(folder,entry.name);
    if(entry.isDirectory()) {scan(file);continue;}
    if(!/\.jsx?$/.test(file) || file === path.join(root,'i18n/index.js')) continue;
    const ast=parser.parse(fs.readFileSync(file,'utf8'),{sourceType:'module',plugins:['jsx']});
    traverse(ast,{
      CallExpression(p) {
        if(p.node.callee.name !== 't' || p.node.arguments[0]?.type !== 'StringLiteral') return;
        const key=p.node.arguments[0].value;
        if(!/[가-힣]/.test(key)) return;
        if(!messages[key]?.zh || !messages[key]?.es) failures.push(`${file}: missing ${key}`);
      },
      JSXText(p) {if(/[가-힣]/.test(p.node.value)) failures.push(`${file}: unlocalized JSX ${p.node.value.trim()}`);},
    });
  }
}
scan(root);
for(const [key,translations] of Object.entries(messages)) {
  const markers=s => (s.match(/\{\d+\}/g)||[]).sort().join();
  for(const lang of ['zh','es']) if(!translations[lang] || markers(key)!==markers(translations[lang])) failures.push(`${lang}: placeholders differ for ${key}`);
}
if(failures.length) {console.error(failures.join('\n'));process.exit(1);}
console.log(`Validated ${Object.keys(messages).length} Korean/Chinese/Spanish messages and interpolation markers.`);
