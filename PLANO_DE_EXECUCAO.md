# CareerBrain Next — plano de dez execuções

Especificação pública da V1. Somente a fundação da 01 está preparada; publicação,
proteção da main e próximas execuções exigem autorização própria.

## Decisões do produto

Catálogo global universal, perfis/matching/candidaturas privados por usuário.
Android com Google OIDC e identidade estável por issuer+sub; fluxo instalar → login
→ currículo → recomendações, sem questionários ou confirmação de perfil obrigatórios.
Ingresso só por API autenticada de produtor; sem coleta de portal ou leitura de CSV
no núcleo. Publicação verdadeira e contato oficial são obrigatórios. Eventos
originais/republicados têm prova; correções cosméticas não geram novidade.
Só recomendar eventos com published_at >= account_created_at UTC imutável.
Currículo e texto bruto são transitórios; novo currículo mantém a data da conta.
IA externa com evidências e incerteza, sem modelo local ou módulo financeiro interno.
Fila assíncrona idempotente, mais recentes primeiro com prevenção de starvation.
Mostrar afinidade alta e alguma baixa calibrada pelo uso, respeitando elegibilidade.
Candidaturas manuais; novidades ao abrir, sem push obrigatório; TTS existente por
fronteira segregada e sem interferência em outros projetos. Exclusão cobre derivados
com política verificável de backups. API pública HTTPS funciona em rede móvel.
PostgreSQL exclusivo, volumes/backups dedicados; operação separada dos workers de CI.
Código publicável passa por allowlist e revisão; inventários/segredos ficam privados.

## Protocolo uniforme

Autorização nominal → validar entrada/escopo → branch/PR → testes permitidos →
evidências e checkpoint → parar. Deploy, migração produtiva, acesso a credenciais,
tráfego pago, assinatura e alterações externas têm gates próprios. Não ampliar escopo
para contornar falha. Suítes pesadas só nos workers; indisponibilidade bloqueia.

### Execução 01/10 — Fundação, contratos, governança e CI

Entrada: plano aprovado e autorização nominal. Entrega: docs, contratos V1, schemas,
fixtures, CI offline e plano de workers próprios. Aceite: conteúdo auditado, histórico
novo, PR/checks verdes, main protegida e projetos existentes preservados. Publicação
não implica merge. Rollback: fechar PR/reverter branch sem mexer em produção.

### Execução 02/10 — PostgreSQL exclusivo e migrações

Depende da 01 e de workers certificados. Entrega: schema global/privado, fila/outbox,
RLS/papéis mínimos, constraints, índices e scripts de migração/backup. Aceite: negação
cross-tenant sob papéis reais, pool sem vazamento, marco imutável, migration/rollback
compatível e restore descartável. Banco só de teste. Rollback no ambiente descartável.

### Execução 03/10 — API base, OIDC e identidade

Depende de 01–02 e configuração OAuth pública aprovada. Entrega: prova Google,
provisionamento idempotente, sessões revogáveis e autorização fail-closed. Aceite:
tokens inválidos/expirados/audience errada negados, concorrência e reinstalação sem
contas duplicadas. Rollback da versão controlada, sem apagar dados reais.

### Execução 04/10 — Ingestão contratual autenticada

Depende de 01–03 e direitos de dados reais quando utilizados. Entrega: lote atômico,
proveniência, lifecycle, idempotência/recibos e outbox transacional. Aceite: rejeição
de data/contato/prova inválidos, replay concorrente e crash sem persistência parcial.
Sem scraping/CSV pelo núcleo. Rollback desabilita endpoint e preserva eventos aceitos.

### Execução 05/10 — Fila e classificação global

Depende da 04; tráfego real exige gate financeiro/privacidade do provedor.
Entrega: leases/fencing/retries/aging e cache versionado. Aceite: corpus multissetorial,
evidências de requisitos, falhas e quotas tratadas sem score fictício. Benchmark real
exige autorização; sem promessa de throughput. Rollback suspende worker sem perder fila.

### Execução 06/10 — Currículo transitório e perfil privado

Depende de 02–05, fila/adaptador e gates de dados pessoais/IA. Entrega: upload seguro,
parser limitado, TTL, limpeza, perfil validado com geração/epoch. Aceite: descarte
em sucesso/falha/cancelamento/interrupção, nenhum bruto em fila/log/backup, CAS evita
sobrescrita atrasada; novo currículo mantém account_created_at. Rollback suspende upload.

### Execução 07/10 — Matching privado e corte temporal

Depende de 04–06. Entrega: elegibilidade, afinidade, motivos e projeções versionadas.
Aceite: antes/igual/depois da conta, importação atrasada, republicação comprovada,
correção cosmética e mudança de perfil sem retroativos; isolamento. Rollback suspende
recomputação e só serve projeções atuais que continuem elegíveis.

### Execução 08/10 — APIs móveis, candidaturas, sincronização e exclusão

Depende de 03–07. Entrega: paginação, cursor por disponibilização, estados manuais,
leitura e expurgo. Aceite: classificação tardia não se perde, múltiplos dispositivos,
retry sem duplicação, exclusão concorrente e restore sem ressurreição de dados.
Catálogo global preservado. Rollback suspende endpoints mantendo schema compatível.

### Execução 09/10 — APK e testes controlados

Depende de 03 e 06–08. Entrega: cliente Android e adaptadores fake quando necessário.
Aceite: build, instrumentação, retomada, reinstalação controlada e erros de rede.
Assinatura real só fora do CI e autorizada. Google real, HTTPS público, TTS real e
4G/5G são aceite da 10. Rollback usa APK de teste compatível; não altera outros apps.

### Execução 10/10 — Certificação integrada e entrega

Depende de 01–09 aceitas, CI, recursos e gates externos comprovados. Entrega:
implantação aprovada, versões imutáveis, observabilidade, backup/restore e API HTTPS.
Aceite: Google verdadeiro → currículo → recomendações → candidatura → sync → TTS →
exclusão em 4G/5G; isolamento, logs mínimos e rollback demonstrados. Dados reais
precisam de direitos e publicação posterior à conta; fixtures só em testes segregados.
Rollback distingue exposição HTTP, imagens, workers, schema e dados.

## Correções preservadas

CI independente; 09/10 sem ciclo; gates por uso real; contratos de lifecycle/replay/
sync/exclusão antes do banco; dependência 06 inclui 05; TTS segregado; aceites
reproduzíveis e rollback por camada. Nenhuma execução se autoautoriza.
