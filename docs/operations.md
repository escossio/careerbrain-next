# Operação e rollback planejados

01: fechar PR ou reverter commits na branch, preservando evidências aprovadas.
Não apagar o repositório nem alterar main como forma automática de rollback.

02–08: somente ambientes descartáveis autorizados de CI. Migrações numeradas e
checksums, reaplicação sem efeitos duplicados e compatibilidade expand/contract.
Migrações destrutivas não são rollback padrão. Nenhum banco produtivo antes da 10.

10: backup lógico criptografado e teste de restore antes da promoção; destino fora
do mesmo SSD/host definido e comprovado antes de provisionar. Dados persistentes
Next dedicados em armazenamento próprio, sem mover volumes existentes. Medir capacidade e
limitar CPU/RAM/parser/conexões/concurrency antes do rollout; espaço disponível
isolado não certifica I/O ou disponibilidade comercial.

Rollback por camada:

1. Exposição: restaurar placeholder 503 mediante autorização da 10.
2. Aplicação: voltar imagem por digest e configuração compatível com schema/fila.
3. Workers: suspender consumidores e preservar eventos; não perder lotes aceitos.
4. Schema: migrar aditivamente ou aplicar reparo testado; downgrade destrutivo exige
   autorização e backup. Reverter imagem não reverte schema nem cobrança externa.
5. Dados: restaurar em ambiente isolado, reaplicar ledger de exclusão antes de
   qualquer leitura/egress; jamais sobrescrever volume ativo ou dados de outro projeto.

Backups privados cifrados: retenção máxima proposta de 30 dias, active-data erase
em até 24h; jobs e sessões bloqueados imediatamente. O ledger mínimo de exclusão
existe apenas pelo período necessário para sanear backups e também expira. Sem
promessa de apagar sistemas do provedor externo por apagar um arquivo localmente.
Esses parâmetros são especificação V1 e exigem comprovação antes de dados reais.
