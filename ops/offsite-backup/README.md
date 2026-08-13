# DPMS offsite backup

Контур создает зашифрованную копию PostgreSQL и `uploads` на съемном
носителе отдельного Ubuntu-компьютера. Ротация выполняется только после
успешного создания и проверки новой копии; сохраняются последние три версии.

## Гарантии

- production credentials не передаются на backup-компьютер и не входят в архив;
- поток идет через SSH непосредственно в `age`, без открытого архива на USB;
- запись разрешена только на реально смонтированный `rw` носитель с ожидаемым
  UUID или LABEL и marker-файлом;
- незавершенная запись имеет имя `.partial` и не участвует в ротации;
- каждая копия получает SHA-256 sidecar;
- restore drill всегда поднимает одноразовый PostgreSQL-контейнер и не умеет
  подключаться к production DB;
- timer проверяет расписание ежедневно, но создает backup только спустя 14 суток
  после последнего успеха. После ошибки новая попытка будет на следующий день;
- uploads и DB снимаются при короткой write-паузе backend. Предварительный
  `rsync` сокращает эту паузу до финальной дельты и времени `pg_dump`.

## Подготовка Ubuntu 24.04

1. Запустить `sudo ./install.sh install`. Installer проверяет Ubuntu 24.04,
   устанавливает runtime-зависимости и создает системного пользователя
   `dpms-backup`; Docker должен быть установлен заранее для restore drill.
2. Создать отдельную age-identity вне USB и сохранить резервную копию identity
   отдельно. На USB хранится только зашифрованный архив.
3. Настроить SSH alias к production без пароля и разрешить строго команду
   `/opt/dpms-tools/dpms-export-backup.sh` через `sudoers`.
4. Постоянно монтировать носитель, например в `/mnt/dpms-backup`, записать его
   UUID или LABEL в config и создать:

   ```bash
   printf 'DPMS_OFFSITE_BACKUP_V1\n' | sudo tee /mnt/dpms-backup/.dpms-offsite-backup-target
   sudo chmod 0600 /mnt/dpms-backup/.dpms-offsite-backup-target
   ```

5. Установить скрипты и unit-файлы, затем создать
   `/etc/dpms-offsite-backup.conf` по примеру. Конфигурация должна иметь mode
   `0600`; private identity должен читаться только `dpms-backup` и не должен
   размещаться в git или рядом с архивами. Каталог на USB должен быть доступен
   на запись пользователю `dpms-backup`.
6. Сначала выполнить ручной backup и restore drill. Только после зеленого
   результата включить timer командой `sudo ./install.sh enable`.

## Ручная проверка

```bash
sudo /usr/local/sbin/dpms-offsite-backup.sh
sudo /usr/local/sbin/dpms-offsite-restore-drill.sh \
  /mnt/dpms-backup/dpms-offsite/dpms-YYYYMMDDTHHMMSSZ.tar.zst.age
sudo systemctl enable --now dpms-offsite-backup.timer
systemctl list-timers dpms-offsite-backup.timer
```

Размер носителя рассчитывается как `3 x максимальный полный backup + 20%`.
Для квоты 50 MiB на пользователя 128 GB является минимальным практичным
вариантом до примерно 500 пользователей; для запаса рекомендуется 256 GB.
