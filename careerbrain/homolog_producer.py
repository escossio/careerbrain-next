"""Synthetic-only producer; no external collection or source data."""
from __future__ import annotations
import hashlib,json,os,urllib.request
from datetime import datetime,timezone
from uuid import UUID,uuid5
NS=UUID('11111111-1111-1111-1111-111111111111'); SOURCE=str(uuid5(NS,'source')); AUTH=str(uuid5(NS,'authorization')); EVID=str(uuid5(NS,'evidence'))
def records():
 now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
 roles=['Software Engineer','Python Developer','Data Analyst','DevOps Engineer','SRE Engineer','Network Engineer','Cloud Engineer']
 for i in range(141):
  title=roles[i%len(roles)]+' Synthetic '+str(i+1); desc=f'Synthetic homologation vacancy {i+1}. Python, cloud, automation, observability and infrastructure responsibilities are explicitly documented for deterministic classification.'
  yield {'operation':'publish','vacancy':{'source_id':SOURCE,'source_vacancy_id':f'synth-{i+1:03d}','title':title,'organization':'CareerBrain Synthetic Labs','description':desc,'requirements':['Python','automation','cloud'], 'modality':['remote','hybrid','onsite'][i%3],'location':'Synthetic City/BR','employment_type':['internship','employee','apprentice'][i%3],'access':{'kind':'https','value':f'https://homolog.invalid/apply/synth-{i+1:03d}'},'event':{'source_event_id':f'synth-event-{i+1:03d}','kind':'original','published_at':now,'provenance':{'authorization_id':AUTH,'evidence_id':EVID,'evidence_sha256':hashlib.sha256(b'careerbrain-synthetic-homolog').hexdigest(),'evidence_kind':'source_statement','evidence_url':'https://homolog.invalid/evidence/careerbrain-synthetic','observed_at':now,'extractor_version':'synthetic-homolog-v1'}}}}
def submit(batch_id, rows):
 body=json.dumps({'schema_version':'careerbrain.ingestion.v1','batch_id':batch_id,'records':rows},sort_keys=True,separators=(',',':')).encode(); req=urllib.request.Request(os.environ['CBN_INGEST_URL'],body,{'Authorization':'Bearer '+os.environ['CBN_PRODUCER_TOKEN'],'Content-Type':'application/json','Idempotency-Key':batch_id},method='POST')
 with urllib.request.urlopen(req,timeout=10) as response:return json.loads(response.read())
def main():
 rows=list(records()); out=[submit('synthetic-141-a',rows[:100]),submit('synthetic-141-b',rows[100:])]; print(json.dumps({'generated':len(rows),'receipts':out},separators=(',',':')))
if __name__=='__main__':main()
