# STATUS — CareerBrain Next

## Checkpoint da passada 02

**Estado aplicado na main após checks verdes e merge deste PR: 2/10 validadas.**
Antes do merge, este checkpoint representa o aceite SQL concluído e a conclusão
condicionada ao CI obrigatório e merge protegido.

- 01 certificada e merged; fundação, contratos V1 e CI offline aprovados.
- 02: PostgreSQL 16, papéis mínimos/RLS, fila/outbox, migrações/checksums e índices.
  18 testes SQL e restore/ledger aprovados em worker isolado, com dados sintéticos.
- 03 autorizada após certificação/merge da 02. 04–10 não autorizadas nesta sequência.

Ver docs/database.md e docs/evidence-02.md. Nenhum banco produtivo, deploy público,
chamada de IA ou mudança de credenciais/permissões de integrações.
Auditoria geral de GitHub Apps permanece atividade de segurança independente.
