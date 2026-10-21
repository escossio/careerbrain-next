# Currículo transitório e perfil privado — execução 06

O upload autenticado recebe somente PDF até 5 MiB. O parser determinístico desta
passada valida assinatura, EOF, páginas, limite de texto e rejeita criptografia
e conteúdo ativo. Ele trabalha apenas com fixtures sintéticas e não é um parser
de produção geral, nem chama IA ou rede.

O arquivo e o texto extraído ficam em armazenamento efêmero de processo; o
PostgreSQL contém apenas handle UUID, tenant, geração, epoch, prazo e estado.
O prazo absoluto é de quinze minutos, sem renovação, e há no máximo três
tentativas. A limpeza remove bytes em sucesso, falha final, cancelamento,
expiração, perda após reinício e varredura de resíduos.

A migração 007 adiciona funções de fronteira para criar, reivindicar, concluir,
fazer retry, cancelar e expirar jobs. Elas aplicam lease/fencing e compare-and-set
de geração/epoch antes de salvar o perfil. Uma troca de currículo ou cancelamento
invalida resultado atrasado; `account_created_at` permanece imutável.

`careerbrain.profile.v1` continua compatível. A nova versão explícita
`careerbrain.profile.v2` resolve a ambiguidade: `READY` exige ao menos um
atributo comprovado e `UNCERTAIN` exige atributos vazios. Assim, ausência de
evidência não cria a qualificação artificial `unknown`.

O worker CI verifica apenas seu próprio ambiente descartável: rede desligada,
limite de memória sem swap de container, core dump desativado e temporários em
tmpfs. Isso não certifica controles de produção; prova do proxy, parser e host
reais permanece gate de privacidade antes de aceitar documentos reais.
