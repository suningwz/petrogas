#!/bin/bash

# vars
BACKUP_DIR=~/dB
DB_NAME=smp_prod_20012020
DB_PASSWORD=admin
FILESTORE=/home/disruptsol/odoo-dev/SMP/filestore/filestore
BACKUP_DB_NAME=${DB_NAME}_$(date +%m%d%Y_%H_%M)

# create a backup directory
mkdir -p ${BACKUP_DIR}

# create a backup
pg_dump -Fc -f ${BACKUP_DB_NAME}.dump ${DB_NAME}
tar cjf ${BACKUP_DIR}/${BACKUP_DB_NAME}.tgz ${BACKUP_DB_NAME}.dump ${FILESTORE}/${DB_NAME}

# delete old backups
find ${BACKUP_DIR} -type f -mtime +8 -name "${DB_NAME}.*.tgz" -delete

# delete all file wich is no backups
 find ${BACKUP_DIR} -type f  -name "*.dump" -delete

# Transfert FTP
lftp ftps://192.168.1.20 -p 990 -u smp,Smp@2020 << EOF
put ${BACKUP_DIR}/${BACKUP_DB_NAME}.tgz
echo "Terminé"


