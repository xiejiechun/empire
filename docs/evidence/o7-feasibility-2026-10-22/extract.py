"""Keep bounded, relevant quotations; never archive entire successful documents."""
import hashlib
import json
from pathlib import Path
from pypdf import PdfReader

OUT=Path(__file__).parent
selection={
 '600590':[(1,'股票代码：','3、资产过户情况'),(6,'三、本次发行的实施情况','四、发行结果'),
           (15,'五、独立财务顾问和法律顾问意见',None),(16,'金成功与否','六、本次发行前后'),
           (17,'七、公司股本结构变化','八、管理层讨论')],
 '300176':[(1,'证券代码：','一、公司基本情况'),(3,'本 次 配 股 以','（四）发行方式'),
           (4,'股份数量为','（六）发行价格'),(5,'根据中国证券登记','（十三）'),
           (5,'三、本次新增股份上市情况',None),(6,'股份类别','（二）本次发行后')],
 '001228':[(9,'一、发行类型和面值','二、本次发行履行'),(10,'本次向特定对象发行股票最终发行价格','四、发行方式'),
           (12,'十、新增股份登记托管情况','十一、发行对象'),(17,'第四节 本次股份变动情况','二、本次发行前后')],
 '601127':[(1,'证券代码：','一、本次发行概况'),(2,'（二）本次发行的情况','（三）募集资金'),
           (3,'2、股份登记情况','（四）资产过户情况'),(9,'四、本次发行前后本公司股本结构变动表','五、管理层讨论')]
}
probes=json.loads((OUT/'pdf-probe.json').read_text('utf8'))
results=[]
for req in probes['requests']:
 p=Path(req['artifact']['path']); code=p.name.split('-')[1]; reader=PdfReader(p)
 excerpts=[]
 for n,start,end in selection[code]:
  text=reader.pages[n-1].extract_text()
  assert start in text,(code,n,start)
  text=text[text.index(start):]
  if end is not None:
   assert end in text,(code,n,end)
   text=text[:text.index(end)]
  excerpts.append(dict(pdf_page=n,text=text))
 results.append(dict(security=code,url=req['url'],sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                     bytes=p.stat().st_size,pages=len(reader.pages),observed_at=req['acquired_at'],excerpts=excerpts))
(OUT/'excerpts.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
print('Bounded quotations extracted from four PDF documents; full files remain temporary only.')
