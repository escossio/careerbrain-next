# Persistência descartável e isolamento SQL

PostgreSQL 16 e Psycopg 3.3.6; Python 3.13. A passada 02 implementa persistência e
provas em CI. Não provisiona banco produtivo ou API pública. Runtime e migração
produtivos, credenciais, volumes duráveis e backup externo continuam gates da 10.

## Modelo e papéis

- identity: conta, marco imutável, issuer+sub canônico e provisionamento concorrente.
- catalog: fontes/autorizações/evidências, vagas, eventos, revisões e semântica global.
- private: tenant pessoal, perfil profissional, candidaturas, projeções e feed.
- queue: filas global/privada separadas e outbox transacional.
- ops: recibos idempotentes, migrações/checksums, auditoria mínima e ledger de exclusão.

cb_owner é NOLOGIN; cb_migrator pode assumir somente o owner durante uma transação
de migração. cb_auth executa provisionamento sem acesso a perfis. cb_api e
cb_private_worker usam tenant transacional. cb_global_worker não acessa dados
privados. cb_privacy só insere ledger e executa expurgo controlado. Runtimes são
NOSUPERUSER/NOBYPASSRLS/NOCREATEROLE/NOCREATEDB e não herdam owner.

RLS é forçada nas tabelas de identidade/tenant, inclusive filas privadas. Ausência
ou UUID inválido nega o escopo; estado DELETING nega imediatamente. O contexto é
instalado pelo serviço com SET LOCAL, depois de autorizar a sessão, e o pool executa
RESET ROLE/RESET ALL antes do reuso. A aplicação conserva sua responsabilidade de
autorização e parametrização de SQL: quem controla a credencial SQL do runtime
consegue definir GUCs e precisa ser tratado como parte confiável da fronteira.

O marco da conta vem do banco, não pode ser atualizado, e provisionamento sob
advisory lock mais unique issuer+sub preserva IDs em concorrência. Eventos têm
instantes e identidades imutáveis, recebimento do servidor, prova referenciada e
republicação estritamente posterior com outra evidência. Recomendações exigem
publicação elegível; encerramento/retirada invalida leitura. A sequência por tenant
é obtida sob lock de linha mantido até commit para impedir ultrapassagem de commits.
Fila privada só possui handle, tenant, geração, epoch, prazo e controle de execução;
não tem coluna para PDF/texto bruto ou payload livre. Perfil atrasado falha por
CAS de geração/epoch e versão. Processamento de IA e endpoints são passadas futuras.

## Migração, rollback e restore

001 cria a fundação; 002 adiciona índices. Checksums e advisory lock serializam
reaplicação. Checksum divergente é erro; voltar de 002 a 001 remove apenas índices,
preserva dados e permite reaplicação. Não há downgrade destrutivo da fundação.
O runner atual aceita somente nomes de bancos descartáveis com prefixo cbn_test_.
Bootstrap de papéis serve apenas ao cluster descartável exclusivo do job.

O teste efetua pg_dump custom, exclusão no original, pg_restore em outro banco
isolado e reaplicação de ledger antes da primeira leitura de runtime. Verifica
que tenant excluído não ressuscita, outro tenant e catálogo permanecem, assim como
marco e RLS. Isso não certifica retenção real de 30 dias, criptografia/custódia ou
backup de produção; esses controles dependem do ambiente autorizado da 10.

## Fluxo próprio de workers

ci/worker_run.py e tools/ci_worker.py recebem apenas fonte pública commitada,
identificada por SHA. O controlador usa SSH existente e um caminho de lock
fornecido fora do Git; não altera registros, runners, scripts ou configurações
compartilhadas. O lock existente é aberto somente para coordenação do uso do host.

Imagem de cliente por digest, dependências binárias com hashes e etapa de instalação
separada dos testes. Banco/cliente: network=none, nenhum TCP publicado, sem
capabilities, no-new-privileges, root filesystem somente leitura, limites de
CPU/RAM/PIDs. Dados PostgreSQL ficam em tmpfs; cliente sem privilégio usa apenas
socket Unix e código somente leitura. Nenhum socket Docker ou segredo é montado.
O controle Docker fica no dispatcher de confiança, fora dos containers de testes.
CI opera somente com fixtures sintéticas, autenticação local trust e sem rede;
essa autenticação não é configuração de produção.

A referência Compose está em ci/compose.postgres.yml; o executor usa os mesmos
controles por Docker CLI e inspeciona o container real antes dos testes. A evidência
inclui SHA, digest, isolamento, resultados, hashes, remoção do banco e preservação
dos demais containers. Logs detalhados, nomes de workers e caminhos ficam privados.
O executor nunca faz prune e mantém evidências privadas do job para recuperação.

Os checks rápidos contracts/repository-policy permanecem independentes de banco.
A suíte SQL explícita tests/integration/database_cases.py é executada exclusivamente
no worker; a verificação offline não importa ou simula essa suíte. Ausência de
worker bloqueia a certificação SQL, sem fallback pesado no controlador.
