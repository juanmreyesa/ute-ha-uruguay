const { chromium } = require('playwright'); const fs=require('fs');
(async () => {
  const svg = fs.readFileSync('zvet-rollup.svg','utf8');
  const b = await chromium.launch();
  let p = await b.newPage({ viewport:{width:850,height:2000}, deviceScaleFactor:3 });
  await p.setContent(`<body style="margin:0">${svg}</body>`); await p.screenshot({path:'zvet-rollup.png'});
  p = await b.newPage();
  await p.setContent(`<style>@page{size:850mm 2000mm;margin:0}body{margin:0}svg{width:850mm;height:2000mm;display:block}</style>${svg}`);
  await p.pdf({width:'850mm',height:'2000mm',printBackground:true}); 
  await p.pdf({path:'zvet-rollup.pdf',width:'850mm',height:'2000mm',printBackground:true});
  await b.close();
})();
