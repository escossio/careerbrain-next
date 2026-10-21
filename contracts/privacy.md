# Currículo transitório, perfil e exclusão V1

V1 aceita PDF (tipo real validado), até 5 MiB, 50 páginas e 200.000 caracteres
extraídos. Arquivos cifrados, inválidos, conteúdo ativo ou expansão excessiva são
rejeitados com código sanitizado. PDF é o formato inicial defensivo; novos formatos
exigem contrato/testes próprios. Parser sem rede, usuário sem privilégios, limites
de CPU/memória/tempo; nenhum upload dispara IA no processo HTTP.

Área temporária privada em memória/tmpfs, tenant isolado, fora de volumes duráveis,
swap/dumps/backups e proxy body spool em disco. A exclusão de um arquivo de tmpfs
não garante privacidade se páginas forem para swap: gate de deploy exige demonstrar
memória protegida contra swap/core dump, inclusive proxy/parser e texto extraído.
Não alegar descarte seguro antes de comprovar esses controles no ambiente de execução.

TTL absoluto de 15 minutos desde recepção, até 3 tentativas dentro desse prazo.
Fila durável contém apenas handle opaco, owner, geração, epoch de exclusão e prazo.
Arquivo e texto bruto ficam só na área efêmera. Reboot/perda do handle → EXPIRED,
limpeza e novo upload; nunca usar um perfil antigo para fingir que extração ocorreu.
Sucesso/falha/cancelamento apagam original e texto; sweeper até 60s detecta resíduos
após interrupção, sem renovar TTL. Sem resíduo bruto em DLQ/log/trace/cache/provedor
de arquivos. Envio à IA exige G-PRIVACY/G-AI e política de retenção comprovada.

Upload recebe `request_id`, consent_version e metadados, sem tenant no body.
Retentativa da mesma operação não cria outra geração. Novo request avança geração.
Somente geração atual, conta ACTIVE e epoch correspondente podem gravar resultado;
commit é compare-and-set. Extração atrasada não sobrescreve versão mais nova.
Saída inválida preserva último perfil válido e informa falha. Perfil guarda só
atributos profissionais, evidências curtas necessárias e incerteza; não texto integral,
nome/telefone/endereço/documentos pessoais irrelevantes. Novo currículo mantém marco.
`careerbrain.profile.v2` representa `UNCERTAIN` com atributos vazios; `READY`
exige atributos comprovados. O V1 permanece imutável para consumidores existentes.

## Exclusão

`DELETE /v1/me` idempotente por request_id: na transação inicial marcar DELETING,
incrementar epoch, revogar sessões e impedir login/recriação até fim do expurgo.
Workers cancelam e revalidam epoch antes de commit e egress. Excluir identidade
local, vínculos, perfis/versões, matching, candidaturas, preferências, áudio/cache,
temporários, jobs e referências pessoais em observabilidade em até 24h.

Recibo opaco informa estado e prazos sem exigir sessão revogada; consulta exige
capability de exclusão específica, expira ao concluir, não dá acesso a outros dados.
Seu material secreto será emitido em runtime, nunca em fixtures ou nesta passada.
Catálogo global fica, exceto eventual dado pessoal do titular que precise expurgo.

Backups expiram em até 30 dias. Ledger mínimo cifrado e separado, contendo apenas
identificadores necessários à sanitização, fica disponível enquanto existir backup
afetado. Restore é isolado; ledger é reaplicado antes de liberar leitura/worker/egress.
Após expiração comprovada das cópias e expurgo do ledger, marcar COMPLETE e remover
capability. Não conservar tombstone identificável para sempre. Dependências externas
e obrigações de retenção excepcionais devem ser registradas antes de aceitar dados reais.
