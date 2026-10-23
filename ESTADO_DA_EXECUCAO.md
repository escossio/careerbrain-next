# CareerBrain Next — estado da execução

Checkpoint certificado da passada 09. As passadas 01–09 estão certificadas
na main. CI Android, testes unitários, lint, APKs e instrumentação Compose
no Android 14 passaram antes do merge protegido.

| Passada | Estado |
| --- | --- |
| 01 | CERTIFICADA E MERGED; 49 testes e dois checks aprovados |
| 02 | CERTIFICADA E MERGED; 18 testes SQL e restore/ledger aprovados |
| 03 | CERTIFICADA E MERGED; 12 testes de autenticação e IDs públicos aprovados validados sinteticamente |
| 04 | CERTIFICADA E MERGED; 12 testes de ingestão e gates SQL aprovados no worker |
| 05 | CERTIFICADA E MERGED; PR #7, 11 testes novos, regressões e dois checks aprovados |
| 06 | CERTIFICADA E MERGED; PR #9, 11 testes novos, regressões e dois checks aprovados |
| 07 | CERTIFICADA E MERGED; PR #11, CI03 (5 matching e regressões), 51 offline e checks verdes |
| 08 | CERTIFICADA E MERGED; PR #13, migração 010, CI03 (8 matching e regressões) e checks verdes |
| 09 | CERTIFICADA E MERGED; PR #15, Android CI + 2 testes instrumentados PASS |
| 10 | EM_ANDAMENTO; cliente HTTP/Google configurável, fronteira TTS fail-closed e smoke WSGI loopback preparado; execução CI03 pendente |

**9/10 validadas.** Evidências públicas em docs/evidence-02.md,
docs/evidence-03.md, docs/evidence-04.md, docs/evidence-05.md e docs/evidence-06.md;
inventários e logs operacionais ficam privados. Os PRs #9, #11 e #15 passaram nos checks
obrigatórios e foram incorporados sem bypass da proteção da main.
A autorização sequencial não permite novo custo, credencial, produção, deploy ou
mudança de produto. A auditoria geral de Apps foi retirada dos gates pelo proprietário.
O checkpoint inicial da 10 passou 53 testes offline leves no AGT; a execução pesada
permanece reservada ao worker dedicado e não certifica integração real.
O smoke da homologação isolada usa somente fonte commitada, banco `cbn_test_*`, socket
UNIX e HTTP loopback dentro do cliente do worker; não foi executado no control plane
nem certificado até retorno da execução externa. Não autoriza URL Android local,
exposição pública, DNS, proxy, TLS, segredo, backup persistente ou 4G/5G.
Compilação Python, 54 testes offline, política pública e `diff --check` passaram nesta
branch; a prova HTTP real continua reservada ao CI03.
