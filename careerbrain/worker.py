"""Bounded deterministic workers for isolated synthetic homologation."""
from __future__ import annotations
import json, logging, os, signal, time
from .classification import ClassificationConfig, DeterministicClassifier, GlobalClassifier
from .db import tenant_pool
from .matching import MatchService

STOP=False
def _stop(*_):
    global STOP; STOP=True
def _need(name):
    value=os.environ.get(name,'')
    if not value: raise RuntimeError('missing worker setting: '+name)
    return value
def main():
    signal.signal(signal.SIGTERM,_stop); signal.signal(signal.SIGINT,_stop)
    global_pool=tenant_pool(_need('CBN_GLOBAL_WORKER_CONNINFO'))
    private_pool=tenant_pool(_need('CBN_PRIVATE_WORKER_CONNINFO'))
    classifier=GlobalClassifier(global_pool, ClassificationConfig('professional-v1','deterministic-v1','synthetic-homolog-v1'), DeterministicClassifier())
    matcher=MatchService(private_pool, private_pool)
    try:
        while not STOP:
            classified=classifier.run_once()
            matched=matcher.process_once()
            if classified or matched:
                print(json.dumps({'component':'careerbrain-worker','classification':classified,'matching':matched}),flush=True)
            else: time.sleep(1)
    finally: global_pool.close(); private_pool.close()
if __name__=='__main__': main()
