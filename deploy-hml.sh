#DEPLOY HML - puxando de ramifica_1
git fetch origin
git checkout -B deploy origin/feat/ramifica_1
git reset --hard origin/feat/ramifica_1
docker compose -p nossotrello_hml down --remove-orphans
docker compose -p nossotrello_hml up -d --build --force-recreate
