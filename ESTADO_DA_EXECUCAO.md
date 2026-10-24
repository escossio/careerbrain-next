# CareerBrain Next — estado da execução

## Marco de homologação ponta a ponta — 24/10/2026

**Comprovado no runtime de homologação e na tela Android; não é certificação
de produção.** O código está registrado na branch
`feat/passada-10-integracao` da PR #17. A observação foi realizada com o
aplicativo CareerBrain Next no POCO X6, após consentimento/login Google e
envio voluntário de currículo em PDF. O usuário visualizou recomendações
privadas com títulos de engenharia de redes, SRE e DevOps e
`EVIDENCED_AFFINITY`, todas explicitamente
`SYNTHETIC/HOMOLOG` e com URLs `homolog.invalid`.

A consulta operacional **sem conteúdo de currículo, identidades nem segredos**
ao PostgreSQL dedicado confirmou, para o tenant do currículo mais recente:

- Currículo: job `DONE`, perfil `READY`, 12 atributos explícitos.
- Catálogo: 141 vagas sintéticas; 141 eventos de republicação de homologação.
- Correlação privada: 141 jobs `MATCH` em `DONE`, 0 pendentes.
- Feed privado: **61 recomendações com afinidade e confiança preenchidas**.
- API, worker e PostgreSQL: containers `healthy` na verificação.

Os commits da PR incluem extrator textual PDF com limites, taxonomia técnica
de redes/telecom/infraestrutura, matching evidenciado, correções de SQL,
API/HTTPS e apresentação/estado no cliente Android. O head técnico
`4203784a599f624a95bc08ad9aefaef436f9c97e` passou aos workflows
`foundation` e `android-debug` do GitHub.

**Fronteiras do resultado:** as 141 vagas são inteiramente fictícias; não
representam ofertas existentes e não se destinam a candidaturas. Os registros
e os artefatos privados permanecem no runtime, fora do GitHub. A coleta real
da Estácio e a autorização/validação de fontes, a qualificação de dados,
testes completos de rede móvel, observabilidade, gates restantes e o merge
protegido da PR #17 **ainda não estão certificados por este marco**.
A correspondência demonstrada utiliza evidências textuais e regras
determinísticas de homologação; este checkpoint não afirma a execução de
dois modelos de IA em produção.


## Atualização de homologação integrada — 23/10/2026

Marco A está comprovado no ambiente local isolado: 141 vagas inteiramente
sintéticas chegaram pela rota HTTPS autenticada em dois lotes, foram persistidas,
classificadas e reenviadas sem duplicação. A distribuição observada foi 121
`READY` e 20 `UNCERTAIN`. O produtor não recebeu privilégio de banco; fontes,
autorizações, 141 evidências/aprovações e contatos foram provisionados por trilha
administrativa idempotente. Evidências privadas e segredos permanecem fora do Git.

Foi corrigida a imagem de runtime para incluir contratos e fechada a fronteira
API/worker do currículo com tmpfs compartilhado, handles opacos e remoção após
processamento. A prova sintética demonstrou perfil `READY`, matching privado e
feed com somente afinidades evidenciadas. Isso não substitui Google real, PDF
voluntário nem prova no POCO X6; esses passos dependem de configuração OAuth e
interação humana e permanecem pendentes antes de certificação.

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

Na continuação local, PostgreSQL persistente e API Gunicorn foram implantados com
migrações, papéis mínimos, SCRAM, healthchecks e backup/restore privados. A prova
confirma somente a malha local isolada; não autoriza fontes, identidade, Android em
rede móvel, DNS, proxy ou certificação da passada 10.
No SHA `1237028`, CI03 aprovou as regressões de banco/restore, autenticação,
ingestão, classificação, currículo, matching e homologação HTTP isolada.
O smoke da homologação isolada usa somente fonte commitada, banco `cbn_test_*`, socket
UNIX e HTTP loopback dentro do cliente do worker; não foi executado no control plane
nem certificado até retorno da execução externa. Não autoriza URL Android local,
exposição pública, DNS, proxy, TLS, segredo, backup persistente ou 4G/5G.
Compilação Python, 54 testes offline, política pública e `diff --check` passaram nesta
branch; a prova HTTP real continua reservada ao CI03.
