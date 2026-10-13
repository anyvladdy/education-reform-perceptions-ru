import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const data = JSON.parse(await fs.readFile(new URL('./pilot_data.json', import.meta.url), 'utf8'));
const outputDir = new URL('./', import.meta.url);
const wb = Workbook.create();
const evidence = wb.worksheets.add('Примеры');
const protocol = wb.worksheets.add('Поиск и границы');
const headers = ['ID', 'Дата публикации', 'Источник', 'Поисковый маркер', 'Содержание — парафраз', 'Исследовательское значение', 'Доступность и ограничения', 'URL', 'Статус проверки'];
const rows = data.records.map(r => r.map((v, i) => i === 1 ? new Date(v + 'T00:00:00Z') : v));
evidence.getRange(`A1:I${rows.length + 1}`).values = [headers, ...rows];
evidence.showGridLines = false;
evidence.getRange(`A1:I${rows.length + 1}`).format.font = {name: 'Arial', size: 10, color: '#172B4D'};
evidence.getRange(`A1:I${rows.length + 1}`).format.verticalAlignment = 'top';
evidence.getRange(`A1:I${rows.length + 1}`).format.wrapText = true;
const widths = [7, 15, 25, 32, 65, 61, 66, 61, 28];
widths.forEach((w, i) => evidence.getRangeByIndexes(0, i, rows.length + 1, 1).format.columnWidth = w);
evidence.getRange(`B2:B${rows.length + 1}`).setNumberFormat('dd.mm.yyyy');
evidence.getRange(`A2:I${rows.length + 1}`).format.rowHeight = 58;
evidence.getRange('A1:I1').format = {fill:'#243B53', font:{name:'Arial', size:10, color:'#FFFFFF', bold:true}, horizontalAlignment:'center', verticalAlignment:'center', wrapText:true, rowHeight:32};
for (let r = 2; r <= rows.length + 1; r++) {
  if (r % 2 === 0) evidence.getRange(`A${r}:I${r}`).format.fill = '#F1F5F9';
}
evidence.tables.add(`A1:I${rows.length + 1}`, true, 'PilotEvidence');
evidence.getRange(`B2:B${rows.length + 1}`).setNumberFormat('dd/mm/yyyy');
evidence.freezePanes.freezeRows(1);
evidence.freezePanes.freezeColumns(3);

const protocolRows = [
 ['Блок', 'Слова, правила или результат', 'Как использовать'],
 ['Границы', '01.01.2018–06.10.2026 включительно. Проверка страниц: 07.10.2026.', 'Публикации после отсечки не включать. Для будущего сбора комментариев также проверять дату каждого сообщения.'],
 ['Периоды', '2018; 2019–2021; 2022–06.10.2026. Внутри последнего периода сохранять год и месяц.', '2019 выделять от 2020–2021 при интерпретации пандемии. Разные по длине периоды нельзя сравнивать по сырым количествам.'],
 ['Метод пилота', 'Целевой поиск по ключевым словам, чтение публичных страниц и проверка части страниц в браузере.', 'Это реестр примеров для выбора источников, не сплошная выгрузка и не выполненный Selenium-парсер. Парафразы отделены от исследовательской интерпретации.'],
 ['Образовательная траектория', 'СПО, среднее профессиональное образование, колледж, техникум, ПТУ, вуз, университет, высшее образование, 9 класс, 10 класс, ОГЭ, ЕГЭ.', 'Соединять с маркером выбора, оценки или ограничения. Учитывать словоформы и написание е/ё.'],
 ['Барьеры', 'не берут, не приняли, не зачисляют, отказ, профильный класс, универсальный класс, конкурс, средний балл, сократили места, платный приём, целевое.', 'Отделять пережитое препятствие от пересказа новости и общей оценки системы.'],
 ['Перенаправление', 'сначала колледж, потом в вуз, после колледжа, без ЕГЭ, другая специальность, рассмотреть альтернативу, посоветовали, отговорили, передумал, передумала.', 'Проверять направление: внутри ВО, ВО→СПО, внутри СПО. Намерение, совет и фактический переход кодировать отдельно.'],
 ['Польза и признание', 'рабочие профессии, рабочие руки, востребованность, дефицит кадров, зарплата, практика, трудоустройство, карьера, престиж, успешный, гарантия.', 'Проверять рационализацию, статусную компенсацию и обещания. Само упоминание слова не доказывает охлаждение.'],
 ['Исторический словарь', 'WorldSkills, Ворлдскиллс, EuroSkills, Молодые профессионалы, Билет в будущее; далее Профессионалитет, Россия — мои горизонты, Профессионалы.', 'Это расширение поискового словаря, не перечень уже проверенных тегов. Новые названия программ не должны создавать ложное отсутствие ранних сообщений.'],
 ['Сопротивление и контрпримеры', 'диплом, корочка, высшее нужно, высшее не нужно, право учиться, жалоба, не согласен, доступность высшего образования, бюджетные места.', 'Собирать позиции в поддержку ВО, добровольный выбор СПО и отказ от предлагаемых альтернатив.'],
 ['Голос семьи', 'мой сын, моя дочь, ребёнок, родители, у меня высшее, сама закончила вуз, сам закончил вуз, не хуже родителей.', 'Определять социальную позицию только по самопредставлению. Собственное ВО родителя нельзя выводить из наличия ребёнка.'],
 ['Теги и сообщества', 'Дополнить исходный список: Учёба/Учеба, Школа, 10 класс, ОГЭ, Лицей, Учитель, Ученики, Диплом, Родители и дети, Юридическая помощь, Лига Педагогов.', 'Часть названий — кандидаты для проверки существования. Поиск только по образовательным тегам пропускает материал P01 в кулинарной теме.'],
 ['Отбор Telegram', 'Отбирать тематические посты по широкому словарю и уточнять релевантность по контексту.', 'При таком дизайне можно анализировать риторику тематического корпуса. Долю темы среди всех постов канала без общего знаменателя рассчитать нельзя.'],
 ['Границы вывода', 'Релевантные примеры найдены. Временная тенденция и причинный эффект государства не оценивались.', 'Не считать число поисковых результатов частотой. Противоположные позиции и связанные посты-ответы сохранять.'],
 ['Telegram', 'Сохранить для официального таймлайна. minprosrf создан 07.04.2022.', '2018–2021 требуют другого официального архива. Дата создания minobrnaukiofficial в пилоте не установлена. Комментарии аудитории этим способом не получены.'],
 ['Пикабу', 'Сохранить для личного опыта, оценок и споров. Есть ранний пример 2018 года и пример октября 2026 года.', 'Без дополнительной подгрузки часто доступен только один комментарий. Доступную часть нельзя называть полным обсуждением.'],
 ['Табитуриент', 'Сохранить условно для консультаций и выбора внутри ВО.', 'Разделять приёмные комиссии и обычных пользователей. Сестринское дело и Фармация в A01 — программы ВО, а не подтверждение направления в СПО.'],
 ['Резерв', 'Eva.ru — семейные обсуждения с датами; РБК — таймлайн и медийная интерпретация; официальные архивы — ранние сообщения.', 'Официальные публикации O01–O02 найдены только в индексе; пригодность сайта для Selenium не подтверждена. Не заменять голос семей новостями СМИ.'],
 ['Проверка начала minprosrf', 'https://t.me/s/minprosrf?before=3', 'В браузере прочитано служебное сообщение Channel created от 07.04.2022.'],
 ['Снимок данных', 'Просмотры и реакции отражают момент чтения страницы, а не автоматически состояние на 06.10.2026.', 'Сохранять время сбора. Поздние редакции исторических сообщений нельзя считать неизменными оригиналами.']
];
protocol.getRange(`A1:C${protocolRows.length}`).values = protocolRows;
protocol.showGridLines = false;
protocol.getRange(`A1:C${protocolRows.length}`).format.font = {name:'Arial', size:10, color:'#172B4D'};
protocol.getRange(`A1:C${protocolRows.length}`).format.wrapText = true;
protocol.getRange(`A1:C${protocolRows.length}`).format.verticalAlignment = 'top';
protocol.getRange(`A1:A${protocolRows.length}`).format.columnWidth = 29;
protocol.getRange(`B1:B${protocolRows.length}`).format.columnWidth = 87;
protocol.getRange(`C1:C${protocolRows.length}`).format.columnWidth = 88;
protocol.getRange(`A2:C${protocolRows.length}`).format.rowHeight = 47;
protocol.getRange('A1:C1').format = {fill:'#243B53', font:{name:'Arial',size:10,color:'#FFFFFF',bold:true}, horizontalAlignment:'center', verticalAlignment:'center', rowHeight:29};
for (let r=2; r<=protocolRows.length; r++) if (r%2===0) protocol.getRange(`A${r}:C${r}`).format.fill = '#F1F5F9';
protocol.freezePanes.freezeRows(1);

if (new Set(data.records.map(r=>r[0])).size !== rows.length || new Set(data.records.map(r=>r[7])).size !== rows.length) throw new Error('Duplicate record identifier or URL');
for (const r of data.records) if (r[1] < '2018-01-01' || r[1] > '2026-10-06') throw new Error('Record outside date window: '+r[0]);
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'Примеры!A1:D5',include:'values',tableMaxRows:5,tableMaxCols:4,maxChars:3000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:20},maxChars:2000})).ndjson);
for (const [sheetName,range,name] of [['Примеры','A1:F5','evidence_preview'],['Примеры','G22:I26','access_preview'],['Поиск и границы','A1:C8','protocol_preview']]) {
  const preview = await wb.render({sheetName,range,scale:1,format:'png'});
  await fs.writeFile(new URL(`${name}.png`,outputDir),new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(fileURLToPath(new URL('Пилот_источников_2018-2026.xlsx',outputDir)));
console.log(JSON.stringify({records:rows.length,verified:data.records.filter(r=>r[8]==='Страница прочитана').length,candidates:data.records.filter(r=>r[8]!=='Страница прочитана').length}));
