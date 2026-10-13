import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';

const root=fileURLToPath(new URL('../stage1/',import.meta.url));
const book=await SpreadsheetFile.importXlsx(await FileBlob.load(root+'База_трёх_источников.xlsx'));
book.recalculate();
const checks=[];
for(const [sheet,file] of [['Telegram','telegram'],['Пикабу','pikabu'],['Табитуриент','tabiturient']]){
  // The importer drops this Excel custom format; reapply the verified original for preview only.
  book.worksheets.getItem(sheet).getRange('C2:C7').format.numberFormat = 'dd.mm.yyyy';
  checks.push((await book.inspect({kind:'table',range:`'${sheet}'!A1:H5`,include:'values,formulas',maxChars:2500,tableMaxRows:5,tableMaxCols:8,tableMaxCellChars:70})).ndjson);
  const preview=await book.render({sheetName:sheet,range:'A1:F7',scale:1.5,format:'png'});
  await fs.writeFile(root+file+'_preview.png',new Uint8Array(await preview.arrayBuffer()));
}
const scan=await book.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:10},maxChars:2000});
checks.push(scan.ndjson);
await fs.writeFile(root+'workbook_visual_check.ndjson',checks.join('\n'),'utf8');
console.log('Three sheets rendered and inspected.');
