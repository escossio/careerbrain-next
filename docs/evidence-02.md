# Evidências da passada 02

## Execução comprovada

Fonte SQL/runtime testada: 5d205861f50e71b9e2e61a7ba491291db7bd2ae4.
PostgreSQL 16.15 e Python 3.13, imagens por digest e dependências por hash.
Suíte de integração real: **18 testes aprovados em 0,845s**, além do teste de
pg_dump/pg_restore e reaplicação do ledger de exclusão, todos em worker descartável.
Os arquivos SQL/runtime correspondem ao SHA testado; as alterações posteriores
neste checkpoint são somente documentação/lista de arquivos públicos.

Provas: papéis conectados como runtime, NOSUPERUSER/NOBYPASSRLS e sem owner;
RLS forçada; negação de leitura/escrita cross-tenant e sem contexto; contexto
inválido; reset de pool depois de commit/erro; worker global sem acesso privado;
marco da conta imutável; provisionamento concorrente; publicação antes/igual/depois;
evento imutável/republicação; perfil com geração/epoch antigos negado; fila apenas
com handles e TTL; outbox atômica e unicidade; sequência serializada por tenant;
migração concorrente/idempotente, checksum divergente negado e rollback de índices.

Restore em outro banco: ledger aplicado antes de liberar leitura ao runtime;
conta apagada ausente, outro tenant e catálogo preservados; marco e RLS preservados.
Banco em tmpfs, network=none, sem portas, root filesystem read-only, capabilities
removidas, limites CPU/RAM/PIDs e nenhum socket Docker/segredo nos testes. Container
removido ao fim; containers existentes permaneceram iguais ao início do job.

## Falhas corrigidas e limites

Primeira tentativa parou antes do banco por chown desnecessário. A exceção de
source SQL no ignore foi restringida aos arquivos revisados de bootstrap/migração.
Segunda tentativa passou 17 testes SQL, mas importação idempotente do ledger
falhou por privilégio requerido por ON CONFLICT. A correção encapsulou essa operação
em função restrita; não deu leitura direta da tabela. Nova execução passou 18 testes
e restore. Resultados anteriores não foram chamados de aprovação completa.

Os checks públicos contracts/repository-policy devem estar verdes no SHA final do
PR antes de merge. A suíte SQL é separada e comprovada no worker; não é executada
pelo check offline nem no control plane. Logs detalhados e identificação física
ficam na custódia privada, com hashes. CI não contém dados ou credenciais reais.
Estes testes não certificam backup/retensão produtivos, OAuth real, IA, deployment
ou a passada 03. Nenhum serviço produtivo ou projeto existente foi modificado.
