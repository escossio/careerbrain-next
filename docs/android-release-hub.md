# Central compartilhada de versões Android — CareerBrain Next e Andy

## Decisão confirmada em 24/10/2026

Uma única central de distribuição de APKs **na rede privada do laboratório**
deve atender múltiplos projetos. Inicialmente: CareerBrain Next e Andy
(Attention Router). Cada projeto mantém histórico, changelog, SHA-256,
identidade de assinatura e sequência de versões próprios.

A página raiz é um índice dos projetos. As subpáginas são:

- careerbrain/ — versões do CareerBrain;
- andy/ — versões do Andy;
- apk/ — downloads históricos CareerBrain, preservados;
- andy/apk/ — downloads futuros Andy;
- CHANGELOG.txt, SHA256SUMS.txt, manifest.json — manifesto legado CareerBrain;
- andy/CHANGELOG.txt, andy/SHA256SUMS.txt, andy/manifest.json — manifestos Andy.

Na verificação inicial, nove APKs distintos do CareerBrain foram preservados,
e o catálogo Andy foi criado **sem APK publicado**. Páginas e downloads
anteriores foram testados a partir de outro equipamento em sub-rede roteada.

## Política dos artefatos

- APK é imutável por hash. Nenhum release anterior deve ser sobrescrito.
- Todo registro informa alterações, SHA-256, origem e referência de commit.
- A numeração e o changelog são separados por aplicativo.
- O publicador valida pacote Android e certificado de assinatura.
- Para o primeiro Andy, a identidade do pacote e o certificado precisam ser
  aprovados com base em um APK autêntico; nunca inferir a assinatura.
- Rollback do APK não reverte API, dados, tokens nem migrações.
- A atualização do catálogo não altera proteção de branches ou CI.
- Nunca distribuir credenciais, keystores, dados pessoais, sessão ou arquivos
  de configuração sensíveis pelo servidor HTTP.
- Serviço HTTP somente leitura, restrito à LAN por bind e ACL;
  não publicar na Internet, proxy externo ou Cloudflare.

## Preservação e recuperação

O GitHub documenta a **arquitetura compartilhada, as regras e o marco
verificado**. A configuração exata do host, os caminhos físicos e o código
operacional implantado são mantidos no ambiente autorizado, fora do
repositório público, em respeito à política de publicação.

Os APKs permanecem no armazenamento local e exigem backup independente.
O histórico dos builds não é recriado automaticamente a partir dos commits.
O serviço mantém compatibilidade com os URLs anteriores do CareerBrain.

A integração futura com os pipelines Android deve publicar apenas após
validação de build, package name, certificado e checks da branch protegida.
O espaço reservado ao Andy ainda não significa que seu primeiro APK tenha
sido lançado ou homologado.
