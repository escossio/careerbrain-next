# STATUS — CareerBrain Next

## Passada 07 — certificada e integrada

A execução 07 foi concluída pelo PR #11, merge squash
a5fab98cfa8cc28bfb9c0caeb0d4101d47461faa. A branch final
feat/passada-07-matching (979c59327b3814acf817ce43499eb19d535e6c6f)
inclui matching privado e corte temporal, versões e provas negativas
explícitas. REQUIREMENT_UNMET exige requisito obrigatório e atestado
NOT_MET com evidências versionadas; ausência permanece REQUIREMENT_UNKNOWN.
Contratos legados V1 permanecem compatíveis.

CI03 sem rede: PostgreSQL 18, restore/ledger, identidade 12,
ingestão 12, classificação 11, currículo 11 e matching 5: todos PASS.
GitHub Actions run 39849211014: 51 testes offline, checks contracts
e repository-policy SUCCESS no mesmo SHA. Nenhum artefato dos jobs,
credencial, dado real, deploy ou chamada paga. Main protegida.
À época, 08–10 não haviam sido iniciadas.

## Passada 08 — certificada e integrada

PR #13, merge squash `547bcf26d06f89b84f1500984ab72b11d94556f3`, incorporou
a migração aditiva 010: recomendações privadas paginadas, sync com snapshot e
watermark, ACK idempotente, candidaturas manuais com CAS e exclusão com receipt
opaco/capability e ledger. CI03 sem rede aprovou 18 SQL, restore/ledger, 12 de
identidade, 12 de ingestão, 11 de classificação, 11 de currículo e 8 de matching
(incluindo sync multi-dispositivo, CAS concorrente e exclusão). GitHub Actions
run 39858487393 aprovou `contracts` e `repository-policy` no SHA revisado.
Não houve dados reais, produção, deploy, credenciais ou tráfego pago. À época,
09–10 ainda não haviam sido iniciadas.

## Passada 09 — CERTIFICADA E MERGED

PR #15 foi integrado por squash em 02f148078cb74ce6933db5e4d6cdd05efc91b207.
Head de código certificado: 4dc86b39805e3f5a1be4e7189da41e4b1eb21bcb.
Kotlin/Jetpack Compose: identidade sintética, paginação, sincronização de
mudanças/ACK, cursor opaco cifrado, candidaturas manuais, PDF limitado,
remoção local e tratamento de erros. Nenhum backend real foi acessado.

GitHub Actions run 39986129643: contracts e repository-policy PASS.
Run 39986129839: testes unitários Android, lint e build dos APKs
debug e AndroidTest PASS. No emulador chatgpt Android 14 do note-leo,
AndroidJUnitRunner + Compose UI Test: OK (2 tests), cobrindo inicialização,
login sintético, segunda página, salvar, sincronizar e excluir dados locais.
Hashes e logs privados em execution-evidence/09/CERTIFICACAO-09.md.
Sem dados reais, chamadas pagas, contas Google reais ou deploy.
Passada 10 não iniciada. Total 9/10 certificadas.

## Histórico das passadas 01–06

**9/10 certificadas e incorporadas à main.** A passada 06 foi integrada pelo
PR #9, após testes isolados e os checks obrigatórios.

- 01 certificada e merged; fundação, contratos V1 e CI offline aprovados.
- 02: PostgreSQL 16, papéis mínimos/RLS, fila/outbox, migrações/checksums e índices.
  18 testes SQL e restore/ledger aprovados em worker isolado, com dados sintéticos.
- 03: API base, OIDC e sessão revogável; 12 testes de autenticação aprovados
  com identidades sintéticas. Os dois IDs OAuth públicos aprovados foram testados
  com assinatura sintética fora do Git. Login Google real pertence à 10.
- 04: ingestão contratual autenticada com fixtures sintéticas; 12 testes de
  ingestão, 18 SQL, 12 identidade e restauração passaram no worker isolado.
  Direitos de fontes reais permanecem gate externo.
- Ajuste da 04 testado em worker: mesma evidência aprovada por produtores
  distintos resulta em duplicata, sem publicação ou trabalho novo.
- 05 certificada e merged: consumo com lease/fencing, cache global versionado
  e classificação determinística sintética, sem tráfego de IA real. O worker
  isolado aprovou 11 testes novos e as suítes anteriores; `contracts` e
  `repository-policy` passaram no PR #7.
- 06 certificada e merged: PDF transitório, handle opaco, limpeza, CAS de
  geração/epoch e perfil V2. CI03 aprovou 11 testes novos e regressões;
  `contracts` e `repository-policy` passaram no PR #9. A prova de ambiente
  produtivo continua externa.
- 07 certificada e merged; PR #11 e cinco testes de matching aprovados no CI03.
- 08 certificada e merged; PR #13, CI03 e checks obrigatórios aprovados.
- 09 certificada e merged; PR #15, Android CI e instrumentação PASS.
- 10 iniciada em branch isolada `feat/passada-10-integracao`, ainda não certificada.
  O primeiro checkpoint implementou o cliente HTTP Android opt-in por configuração
  de build (HTTPS, timeouts, refresh, operações idempotentes e cursors), o caminho
  Credential Manager/Google Identity com challenge/nonce e uma fronteira TTS
  dedicada fail-closed. O fake da 09 foi preservado para testes. Validação leve no
  AGT: 53 testes offline (contratos, política e TTS), `py_compile` e `diff --check`
  PASS. Build/lint/instrumentação Android e PostgreSQL não foram executados no
  control plane. Não houve chamada Google/TTS/IA, PDF pessoal, credencial, deploy,
  alteração de DNS ou produção. G-OIDC, G-PRIVACY, G-TTS, G-DEPLOY e a prova 4G/5G
  continuam pendentes; G-WORKERS será requerido para as suítes pesadas.

Ver docs/database.md, docs/evidence-02.md, docs/evidence-03.md,
docs/ingestion-04.md e docs/resume-06.md. Nenhum banco produtivo, deploy público,
chamada de IA ou mudança de credenciais/permissões de integrações.
Auditoria geral de GitHub Apps permanece atividade de segurança independente.

## Passada 10 — runtime local persistente (não certificada)

Foi implantado um PostgreSQL dedicado persistente e uma API Gunicorn no ambiente
local isolado, com migrações 1–10, papéis SQL, SCRAM, healthchecks separados e
conexão interna confirmada. Backup custom e restauração em banco temporário
confirmaram as 10 migrações. A API respondeu readiness e erro HTTP sanitizado; o
listener do banco não aceita a interface de identificação externa. Configuração,
secrets, topologia, hashes de backup e logs permanecem privados. O importador CSV,
fontes autorizadas, identidade real, Android em rede móvel e demais gates continuam
pendentes; esta evidência não certifica a passada 10.
O CI03 aprovou no SHA `1237028` banco, restore/ledger, autenticação, ingestão,
classificação, currículo, matching e smoke HTTP isolado; o worker confirmou rede
isolada e preservação dos containers preexistentes.

## Passada 10 — preparação de homologação HTTP isolada

Na branch isolada `feat/passada-10-homologacao-isolada`, foi preparado um harness
WSGI descartável, limitado a loopback, sem logs de requisição e com health mínimo.
O smoke automatizado usa `create_app(...)`, banco `cbn_test_*` e HTTP real somente
dentro do cliente isolado do worker; ele verifica resposta sanitizada de autenticação
e fecha os pools. A expansão do CI03 é pendente de execução externa autorizada; a
regressão anterior `ci03-pr17-regression-01` não foi repetida. Sem deploy, DNS,
Cloudflare, proxy, TLS público, segredo, dado real ou URL Android local. G-DEPLOY e
os demais gates de uso real continuam pendentes; total permanece 9/10 certificadas.
Checks leves desta preparação: compilação Python, 54 testes offline, política pública
e `diff --check` passaram no control plane; isso não valida o smoke do worker.
