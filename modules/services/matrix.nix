{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.homelab;
  matrixState = "${cfg.paths.stateRoot}/matrix";
  whatsappState = "${matrixState}/whatsapp";
  instagramState = "${matrixState}/instagram";
  homeserverName = cfg.domain;
  clientHost = "matrix.${cfg.internalDomain}";
  webHost = "chat.${cfg.internalDomain}";
  whatsappPort = 29318;
  instagramPort = 29320;
  imessageWsproxyPort = 29331;

  cinnyConfig = pkgs.writeText "cinny-config.json" (
    builtins.toJSON {
      defaultHomeserver = 0;
      homeserverList = [ clientHost ];
      allowCustomHomeservers = false;
      featuredCommunities = {
        openAsDefault = false;
        spaces = [ ];
        rooms = [ ];
        servers = [ ];
      };
      hashRouter = {
        enabled = false;
        basename = "/";
      };
    }
  );
  cinnyPackage = pkgs.cinny-unwrapped.overrideAttrs (old: {
    postPatch = (old.postPatch or "") + ''
      substituteInPlace src/client/initMatrix.ts \
        --replace-fail "dbName: 'web-sync-store'" "dbName: 'cinny-web-sync-store'" \
        --replace-fail "new IndexedDBCryptoStore(global.indexedDB, 'crypto-store')" "new IndexedDBCryptoStore(global.indexedDB, 'cinny-crypto-store')" \
        --replace-fail "await mx.initRustCrypto();" "await mx.initRustCrypto({ cryptoDatabasePrefix: 'cinny' });"
    '';
  });
  cinnyWeb = pkgs.runCommand "cinny-homelab-${cinnyPackage.version}" { } ''
    cp -R ${cinnyPackage}/. "$out"
    chmod -R u+w "$out"
    cp ${cinnyConfig} "$out/config.json"
  '';

  yaml = pkgs.formats.yaml { };
  whatsappPackage = pkgs.mautrix-whatsapp.override { withGoolm = true; };
  unstablePkgs = inputs.nixpkgs-unstable.legacyPackages.${pkgs.stdenv.hostPlatform.system};
  instagramPackage = (unstablePkgs.mautrix-meta.override { withGoolm = true; }).overrideAttrs {
    pname = "mautrix-instagram";
    version = "26.07-homelab-${builtins.substring 0 7 inputs.mautrix-meta-homelab.rev}";
    src = inputs.mautrix-meta-homelab;
    subPackages = [ "cmd/mautrix-instagram" ];
    meta = {
      inherit (unstablePkgs.mautrix-meta.meta)
        description
        homepage
        license
        maintainers
        platforms
        ;
      mainProgram = "mautrix-instagram";
    };
  };
  imessageWsproxyPackage = pkgs.callPackage ../../packages/mautrix-wsproxy.nix { };
  whatsappConfig = yaml.generate "mautrix-whatsapp.yaml" {
    network = {
      os_name = "Rishabh's Matrix bridge";
      browser_name = "unknown";
      enable_status_broadcast = false;
      identity_change_notices = true;
      initial_auto_reconnect = true;
      history_sync = {
        max_initial_conversations = 50;
        request_full_sync = false;
      };
    };

    bridge = {
      command_prefix = "!wa";
      personal_filtering_spaces = true;
      private_chat_portal_meta = true;
      bridge_status_notices = "errors";
      relay.enabled = false;
      permissions = {
        "*" = "relay";
        "@rishabh:${homeserverName}" = "admin";
      };
    };

    database = {
      type = "postgres";
      uri = "postgresql:///mautrix-whatsapp?host=/run/postgresql";
      max_open_conns = 5;
      max_idle_conns = 1;
    };

    homeserver = {
      address = "http://127.0.0.1:8008";
      domain = homeserverName;
      software = "standard";
    };

    appservice = {
      address = "http://127.0.0.1:${toString whatsappPort}";
      hostname = "127.0.0.1";
      port = whatsappPort;
      id = "whatsapp";
      bot = {
        username = "whatsappbot";
        displayname = "WhatsApp bridge bot";
      };
      ephemeral_events = true;
      as_token = "$MATRIX_WHATSAPP_AS_TOKEN";
      hs_token = "$MATRIX_WHATSAPP_HS_TOKEN";
      username_template = "whatsapp_{{.}}";
    };

    matrix = {
      message_status_events = true;
      delivery_receipts = true;
      message_error_notices = true;
      sync_direct_chat_list = true;
      federate_rooms = false;
    };

    analytics.token = null;
    provisioning = {
      shared_secret = "disable";
      allow_matrix_auth = false;
      debug_endpoints = false;
      enable_session_transfers = false;
    };
    public_media.enabled = false;
    direct_media.enabled = false;
    backfill = {
      enabled = true;
      max_initial_messages = 100;
      max_catchup_messages = 500;
    };
    double_puppet = {
      allow_discovery = false;
      secrets.${homeserverName} = "as_token:$MATRIX_DOUBLE_PUPPET_AS_TOKEN";
    };
    encryption = {
      allow = true;
      default = true;
      require = true;
      appservice = false;
      msc4190 = false;
      self_sign = true;
      allow_key_sharing = true;
      pickle_key = "$MATRIX_WHATSAPP_PICKLE_KEY";
    };
    env_config_prefix = null;
    logging = {
      min_level = "info";
      writers = [
        {
          type = "stdout";
          format = "json";
        }
      ];
    };
  };

  instagramConfig = yaml.generate "mautrix-instagram.yaml" {
    network = {
      mode = "instagram";
      allowed_modes = [ "instagram" ];
      displayname_template = ''{{or .DisplayName .Username "Unknown user"}}'';
      receive_instagram_typing_indicators = true;
      disable_view_once = false;
      disable_xma_backfill = true;
      disable_xma_always = false;
      min_full_reconnect_interval_seconds = 3600;
      force_refresh_interval_seconds = 72000;
      cache_connection_state = true;
      thread_backfill = {
        batch_count = 5;
        batch_delay = "3s";
      };
    };

    bridge = {
      command_prefix = "!ig";
      personal_filtering_spaces = true;
      private_chat_portal_meta = true;
      bridge_status_notices = "errors";
      relay.enabled = false;
      permissions = {
        "*" = "relay";
        "@rishabh:${homeserverName}" = "admin";
      };
    };

    database = {
      type = "postgres";
      uri = "postgresql:///mautrix-instagram?host=/run/postgresql";
      max_open_conns = 5;
      max_idle_conns = 1;
    };

    homeserver = {
      address = "http://127.0.0.1:8008";
      domain = homeserverName;
      software = "standard";
    };

    appservice = {
      address = "http://127.0.0.1:${toString instagramPort}";
      hostname = "127.0.0.1";
      port = instagramPort;
      id = "instagram";
      bot = {
        username = "instagrambot";
        displayname = "Instagram bridge bot";
        avatar = "mxc://maunium.net/JxjlbZUlCPULEeHZSwleUXQv";
      };
      ephemeral_events = true;
      as_token = "$MATRIX_INSTAGRAM_AS_TOKEN";
      hs_token = "$MATRIX_INSTAGRAM_HS_TOKEN";
      username_template = "instagram_{{.}}";
    };

    matrix = {
      message_status_events = true;
      delivery_receipts = true;
      message_error_notices = true;
      sync_direct_chat_list = true;
      federate_rooms = false;
    };

    analytics.token = null;
    provisioning = {
      shared_secret = "$MATRIX_INSTAGRAM_PROVISIONING_SECRET";
      allow_matrix_auth = true;
      debug_endpoints = false;
      enable_session_transfers = false;
    };
    public_media.enabled = false;
    direct_media.enabled = false;
    backfill = {
      enabled = true;
      max_initial_messages = 100;
      max_catchup_messages = 500;
      unread_hours_threshold = 720;
    };
    double_puppet = {
      allow_discovery = false;
      secrets.${homeserverName} = "as_token:$MATRIX_DOUBLE_PUPPET_AS_TOKEN";
    };
    encryption = {
      allow = true;
      default = true;
      require = true;
      appservice = false;
      msc4190 = false;
      self_sign = true;
      allow_key_sharing = true;
      pickle_key = "$MATRIX_INSTAGRAM_PICKLE_KEY";
    };
    env_config_prefix = null;
    logging = {
      min_level = "info";
      writers = [
        {
          type = "stdout";
          format = "json";
        }
      ];
    };
  };

  imessageMacConfig = yaml.generate "mautrix-imessage-mac.yaml" {
    homeserver = {
      address = "https://${clientHost}";
      websocket_proxy = "wss://${clientHost}";
      ping_interval_seconds = 30;
      domain = homeserverName;
      software = "standard";
      async_media = false;
    };

    appservice = {
      hostname = "127.0.0.1";
      port = null;
      tls_key = null;
      tls_cert = null;
      database = {
        type = "sqlite3-fk-wal";
        uri = "file:mautrix-imessage.db?_txlock=immediate";
      };
      id = "imessage";
      bot = {
        username = "imessagebot";
        displayname = "iMessage bridge bot";
        avatar = "mxc://maunium.net/tManJEpANASZvDVzvRvhILdX";
      };
      ephemeral_events = true;
      as_token = "$MATRIX_IMESSAGE_AS_TOKEN";
      hs_token = "$MATRIX_IMESSAGE_HS_TOKEN";
    };

    imessage = {
      platform = "mac";
      imessage_rest_path = "darwin-barcelona-mautrix";
      imessage_rest_args = [ ];
      contacts_mode = "mac";
      log_ipc_payloads = false;
      hacky_set_locale = null;
      environment = [ ];
      unix_socket = "mautrix-imessage.sock";
      ping_interval_seconds = 15;
      delete_media_after_upload = false;
      bluebubbles_url = null;
      bluebubbles_password = null;
    };

    segment = {
      key = null;
      user_id = null;
    };

    hacky_startup_test = {
      identifier = null;
      message = null;
      response_message = null;
      key = null;
      echo_mode = false;
      send_on_startup = false;
      periodic_resolve = -1;
    };

    bridge = {
      user = "@rishabh:${homeserverName}";
      username_template = "imessage_{{.}}";
      displayname_template = "{{.}} (iMessage)";
      personal_filtering_spaces = true;
      delivery_receipts = true;
      message_status_events = true;
      send_error_notices = true;
      max_handle_seconds = 300;
      device_id = null;
      sync_direct_chat_list = true;
      login_shared_secret = "appservice";
      double_puppet_server_url = "https://${clientHost}";
      backfill = {
        enable = true;
        only_backfill = false;
        initial_limit = 100;
        initial_sync_max_age = 30;
        unread_hours_threshold = 720;
        immediate.max_events = 25;
        deferred = [ ];
      };
      periodic_sync = true;
      find_portals_if_db_empty = false;
      media_viewer = {
        url = null;
        homeserver = null;
        sms_min_size = 409600;
        imessage_min_size = 52428800;
        template = "Full size attachment: %s";
      };
      convert_heif = true;
      convert_tiff = true;
      convert_video = {
        enabled = false;
        ffmpeg_args = [
          "-c:v"
          "libx264"
          "-preset"
          "faster"
          "-crf"
          "22"
          "-c:a"
          "copy"
        ];
        extension = "mp4";
        mime_type = "video/mp4";
      };
      command_prefix = "!im";
      force_uniform_dm_senders = true;
      disable_sms_portals = false;
      reroute_mms_group_replies = false;
      federate_rooms = false;
      caption_in_message = false;
      private_chat_portal_meta = "always";
      encryption = {
        allow = true;
        default = true;
        appservice = false;
        require = true;
        allow_key_sharing = true;
        delete_keys = {
          delete_outbound_on_ack = false;
          dont_store_outbound = false;
          ratchet_on_decrypt = false;
          delete_fully_used_on_decrypt = false;
          delete_prev_on_new_session = false;
          delete_on_device_delete = false;
          periodically_delete_expired = false;
        };
        verification_levels = {
          receive = "unverified";
          send = "unverified";
          share = "cross-signed-tofu";
        };
        rotation = {
          enable_custom = false;
          milliseconds = 604800000;
          messages = 100;
          disable_device_change_key_rotation = false;
        };
      };
      relay = {
        enabled = false;
        whitelist = [ ];
        message_formats = {
          "m.text" = "{{ .Sender.Displayname }}: {{ .Message }}";
          "m.notice" = "{{ .Sender.Displayname }}: {{ .Message }}";
          "m.emote" = "* {{ .Sender.Displayname }} {{ .Message }}";
          "m.file" = "{{ .Sender.Displayname }} sent a file: {{ .FileName }}";
          "m.image" = "{{ .Sender.Displayname }} sent an image: {{ .FileName }}";
          "m.audio" = "{{ .Sender.Displayname }} sent an audio file: {{ .FileName }}";
          "m.video" = "{{ .Sender.Displayname }} sent a video: {{ .FileName }}";
        };
      };
    };

    logging = {
      min_level = "info";
      writers = [
        {
          type = "stdout";
          format = "json";
        }
        {
          type = "file";
          format = "json";
          filename = "./logs/mautrix-imessage.log";
          max_size = 100;
          max_backups = 10;
          compress = true;
        }
      ];
    };
    revision = 0;
  };

  imessageMacConfigExporter = pkgs.writeShellApplication {
    name = "matrix-imessage-export-config";
    runtimeInputs = [ pkgs.envsubst ];
    text = ''
      if [[ $EUID -ne 0 ]]; then
        echo "Run this command through sudo." >&2
        exit 1
      fi

      set -a
      # shellcheck disable=SC1091
      source ${config.sops.templates."matrix-imessage.env".path}
      set +a
      envsubst -i ${imessageMacConfig}
    '';
  };
in
{
  config = lib.mkIf cfg.matrix.enable {
    users.groups.matrix-bridges = { };
    users.users.mautrix-whatsapp = {
      isSystemUser = true;
      group = "matrix-bridges";
      home = whatsappState;
      description = "Mautrix WhatsApp bridge";
    };
    users.users.mautrix-instagram = {
      isSystemUser = true;
      group = "matrix-bridges";
      home = instagramState;
      description = "Mautrix Instagram bridge";
    };
    users.users.mautrix-wsproxy = {
      isSystemUser = true;
      group = "matrix-bridges";
      description = "Mautrix remote appservice WebSocket proxy";
    };
    users.users.matrix-synapse.extraGroups = [ "matrix-bridges" ];
    users.users.postgres.extraGroups = [ "matrix-bridges" ];

    environment.systemPackages = [ imessageMacConfigExporter ];

    sops.templates = {
      "matrix-synapse-secrets.yaml" = {
        owner = "matrix-synapse";
        group = "matrix-synapse";
        mode = "0400";
        content = ''
          registration_shared_secret: ${config.sops.placeholder."matrix-registration-shared-secret"}
        '';
      };

      "matrix-whatsapp.env" = {
        owner = "mautrix-whatsapp";
        group = "matrix-bridges";
        mode = "0400";
        content = ''
          MATRIX_WHATSAPP_AS_TOKEN=${config.sops.placeholder."matrix-whatsapp-as-token"}
          MATRIX_WHATSAPP_HS_TOKEN=${config.sops.placeholder."matrix-whatsapp-hs-token"}
          MATRIX_WHATSAPP_PICKLE_KEY=${config.sops.placeholder."matrix-whatsapp-pickle-key"}
          MATRIX_DOUBLE_PUPPET_AS_TOKEN=${config.sops.placeholder."matrix-double-puppet-as-token"}
        '';
      };

      "matrix-instagram.env" = {
        owner = "mautrix-instagram";
        group = "matrix-bridges";
        mode = "0400";
        content = ''
          MATRIX_INSTAGRAM_AS_TOKEN=${config.sops.placeholder."matrix-instagram-as-token"}
          MATRIX_INSTAGRAM_HS_TOKEN=${config.sops.placeholder."matrix-instagram-hs-token"}
          MATRIX_INSTAGRAM_PICKLE_KEY=${config.sops.placeholder."matrix-instagram-pickle-key"}
          MATRIX_INSTAGRAM_PROVISIONING_SECRET=${
            config.sops.placeholder."matrix-instagram-provisioning-secret"
          }
          MATRIX_DOUBLE_PUPPET_AS_TOKEN=${config.sops.placeholder."matrix-double-puppet-as-token"}
        '';
      };

      "matrix-imessage.env" = {
        owner = "root";
        group = "matrix-bridges";
        mode = "0440";
        content = ''
          AS_TOKEN=${config.sops.placeholder."matrix-imessage-as-token"}
          HS_TOKEN=${config.sops.placeholder."matrix-imessage-hs-token"}
          MATRIX_IMESSAGE_AS_TOKEN=${config.sops.placeholder."matrix-imessage-as-token"}
          MATRIX_IMESSAGE_HS_TOKEN=${config.sops.placeholder."matrix-imessage-hs-token"}
        '';
      };

      "matrix-whatsapp-registration.yaml" = {
        owner = "root";
        group = "matrix-bridges";
        mode = "0440";
        content = ''
          id: whatsapp
          url: http://127.0.0.1:${toString whatsappPort}
          as_token: ${config.sops.placeholder."matrix-whatsapp-as-token"}
          hs_token: ${config.sops.placeholder."matrix-whatsapp-hs-token"}
          sender_localpart: whatsappas
          rate_limited: false
          namespaces:
            users:
              - regex: '^@whatsappbot:${lib.escapeRegex homeserverName}$'
                exclusive: true
              - regex: '^@whatsapp_.*:${lib.escapeRegex homeserverName}$'
                exclusive: true
          de.sorunome.msc2409.push_ephemeral: true
          receive_ephemeral: true
        '';
      };

      "matrix-instagram-registration.yaml" = {
        owner = "root";
        group = "matrix-bridges";
        mode = "0440";
        content = ''
          id: instagram
          url: http://127.0.0.1:${toString instagramPort}
          as_token: ${config.sops.placeholder."matrix-instagram-as-token"}
          hs_token: ${config.sops.placeholder."matrix-instagram-hs-token"}
          sender_localpart: instagramas
          rate_limited: false
          namespaces:
            users:
              - regex: '^@instagrambot:${lib.escapeRegex homeserverName}$'
                exclusive: true
              - regex: '^@instagram_.*:${lib.escapeRegex homeserverName}$'
                exclusive: true
          de.sorunome.msc2409.push_ephemeral: true
          receive_ephemeral: true
        '';
      };

      "matrix-imessage-registration.yaml" = {
        owner = "root";
        group = "matrix-bridges";
        mode = "0440";
        content = ''
          id: imessage
          url: http://127.0.0.1:${toString imessageWsproxyPort}
          as_token: ${config.sops.placeholder."matrix-imessage-as-token"}
          hs_token: ${config.sops.placeholder."matrix-imessage-hs-token"}
          sender_localpart: imessageas
          rate_limited: false
          namespaces:
            users:
              - regex: '^@imessagebot:${lib.escapeRegex homeserverName}$'
                exclusive: true
              - regex: '^@imessage_.*:${lib.escapeRegex homeserverName}$'
                exclusive: true
              - regex: '^@rishabh:${lib.escapeRegex homeserverName}$'
                exclusive: false
          de.sorunome.msc2409.push_ephemeral: true
          receive_ephemeral: true
        '';
      };

      "matrix-double-puppet-registration.yaml" = {
        owner = "root";
        group = "matrix-bridges";
        mode = "0440";
        content = ''
          id: doublepuppet
          url: null
          as_token: ${config.sops.placeholder."matrix-double-puppet-as-token"}
          hs_token: ${config.sops.placeholder."matrix-double-puppet-hs-token"}
          sender_localpart: ${config.sops.placeholder."matrix-double-puppet-sender-localpart"}
          rate_limited: false
          namespaces:
            users:
              - regex: '^@.*:${lib.escapeRegex homeserverName}$'
                exclusive: false
        '';
      };
    };

    services.postgresql = {
      enable = true;
      dataDir = "${matrixState}/postgresql";
      initdbArgs = [
        "--encoding=UTF8"
        "--locale=C"
      ];
      ensureDatabases = [
        "matrix-synapse"
        "mautrix-whatsapp"
        "mautrix-instagram"
      ];
      ensureUsers = [
        {
          name = "matrix-synapse";
          ensureDBOwnership = true;
        }
        {
          name = "mautrix-whatsapp";
          ensureDBOwnership = true;
        }
        {
          name = "mautrix-instagram";
          ensureDBOwnership = true;
        }
      ];
    };

    services.matrix-synapse = {
      enable = true;
      dataDir = "${matrixState}/synapse";
      enableRegistrationScript = true;
      extraConfigFiles = [ config.sops.templates."matrix-synapse-secrets.yaml".path ];
      settings = {
        server_name = homeserverName;
        public_baseurl = "https://${clientHost}/";
        report_stats = false;
        enable_registration = false;
        max_upload_size = "100M";
        url_preview_enabled = false;
        presence.enabled = false;
        federation_domain_whitelist = [ ];
        allow_profile_lookup_over_federation = false;
        allow_device_name_lookup_over_federation = false;
        trusted_key_servers = [ ];
        suppress_key_server_warning = true;
        app_service_config_files = [
          config.sops.templates."matrix-whatsapp-registration.yaml".path
          config.sops.templates."matrix-instagram-registration.yaml".path
          config.sops.templates."matrix-imessage-registration.yaml".path
          config.sops.templates."matrix-double-puppet-registration.yaml".path
        ];
        database = {
          name = "psycopg2";
          args = {
            database = "matrix-synapse";
            user = "matrix-synapse";
            cp_min = 5;
            cp_max = 10;
          };
        };
        listeners = [
          {
            port = 8008;
            bind_addresses = [
              "127.0.0.1"
              "::1"
            ];
            type = "http";
            tls = false;
            x_forwarded = true;
            resources = [
              {
                names = [ "client" ];
                compress = false;
              }
            ];
          }
        ];
      };
    };

    systemd.tmpfiles.rules = [
      "d ${matrixState} 0750 root matrix-bridges - -"
      "d ${matrixState}/synapse 0700 matrix-synapse matrix-synapse - -"
      "d ${whatsappState} 0700 mautrix-whatsapp matrix-bridges - -"
      "d ${instagramState} 0700 mautrix-instagram matrix-bridges - -"
      "d ${matrixState}/postgresql 0700 postgres postgres - -"
      "d ${matrixState}/backups 0700 postgres postgres - -"
    ];

    systemd.services.matrix-postgres-backup = {
      description = "Create consistent Matrix PostgreSQL dumps";
      requires = [ "postgresql.service" ];
      after = [ "postgresql.service" ];
      serviceConfig = {
        Type = "oneshot";
        User = "postgres";
        Group = "postgres";
        UMask = "0077";
        ExecStart = pkgs.writeShellScript "matrix-postgres-backup" ''
          set -euo pipefail
          backup_dir=${lib.escapeShellArg "${matrixState}/backups"}
          ${pkgs.postgresql}/bin/pg_dump --format=custom --file="$backup_dir/matrix-synapse.dump.next" matrix-synapse
          ${pkgs.coreutils}/bin/mv "$backup_dir/matrix-synapse.dump.next" "$backup_dir/matrix-synapse.dump"
          ${pkgs.postgresql}/bin/pg_dump --format=custom --file="$backup_dir/mautrix-whatsapp.dump.next" mautrix-whatsapp
          ${pkgs.coreutils}/bin/mv "$backup_dir/mautrix-whatsapp.dump.next" "$backup_dir/mautrix-whatsapp.dump"
          ${pkgs.postgresql}/bin/pg_dump --format=custom --file="$backup_dir/mautrix-instagram.dump.next" mautrix-instagram
          ${pkgs.coreutils}/bin/mv "$backup_dir/mautrix-instagram.dump.next" "$backup_dir/mautrix-instagram.dump"
        '';
        CapabilityBoundingSet = [ "" ];
        LockPersonality = true;
        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateTmp = true;
        ProtectHome = true;
        ProtectSystem = "strict";
        ReadWritePaths = [ "${matrixState}/backups" ];
      };
    };

    systemd.timers.matrix-postgres-backup = {
      description = "Daily Matrix PostgreSQL backup timer";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "daily";
        Persistent = true;
        RandomizedDelaySec = "30m";
        Unit = "matrix-postgres-backup.service";
      };
    };

    systemd.services.mautrix-whatsapp = {
      description = "Mautrix WhatsApp Matrix bridge";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      requires = [
        "matrix-synapse.service"
        "postgresql.service"
      ];
      after = [
        "matrix-synapse.service"
        "network-online.target"
        "postgresql.service"
        "sops-nix.service"
      ];
      path = [
        pkgs.envsubst
        pkgs.ffmpeg-headless
      ];
      preStart = ''
        umask 0077
        envsubst -i ${whatsappConfig} -o ${whatsappState}/config.yaml
      '';
      serviceConfig = {
        User = "mautrix-whatsapp";
        Group = "matrix-bridges";
        EnvironmentFile = config.sops.templates."matrix-whatsapp.env".path;
        WorkingDirectory = whatsappState;
        ExecStart = ''
          ${whatsappPackage}/bin/mautrix-whatsapp \
            --config=${whatsappState}/config.yaml \
            --registration=${config.sops.templates."matrix-whatsapp-registration.yaml".path} \
            --no-update
        '';
        Restart = "on-failure";
        RestartSec = "10s";
        UMask = "0077";
        CapabilityBoundingSet = [ "" ];
        LockPersonality = true;
        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateTmp = true;
        ProtectClock = true;
        ProtectControlGroups = true;
        ProtectHome = true;
        ProtectHostname = true;
        ProtectKernelLogs = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        ReadWritePaths = [ whatsappState ];
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [ "@system-service" ];
      };
      restartTriggers = [ whatsappConfig ];
    };

    systemd.services.mautrix-instagram = {
      description = "Mautrix Instagram Matrix bridge";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      requires = [
        "matrix-synapse.service"
        "postgresql.service"
      ];
      after = [
        "matrix-synapse.service"
        "network-online.target"
        "postgresql.service"
        "sops-nix.service"
      ];
      path = [
        pkgs.envsubst
        pkgs.ffmpeg-headless
      ];
      preStart = ''
        umask 0077
        envsubst -i ${instagramConfig} -o ${instagramState}/config.yaml
      '';
      serviceConfig = {
        User = "mautrix-instagram";
        Group = "matrix-bridges";
        EnvironmentFile = config.sops.templates."matrix-instagram.env".path;
        WorkingDirectory = instagramState;
        ExecStart = ''
          ${instagramPackage}/bin/mautrix-instagram \
            --config=${instagramState}/config.yaml \
            --registration=${config.sops.templates."matrix-instagram-registration.yaml".path} \
            --no-update
        '';
        Restart = "on-failure";
        RestartSec = "10s";
        UMask = "0077";
        CapabilityBoundingSet = [ "" ];
        LockPersonality = true;
        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateTmp = true;
        ProtectClock = true;
        ProtectControlGroups = true;
        ProtectHome = true;
        ProtectHostname = true;
        ProtectKernelLogs = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        ReadWritePaths = [ instagramState ];
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [ "@system-service" ];
      };
      restartTriggers = [ instagramConfig ];
    };

    systemd.services.mautrix-wsproxy = {
      description = "Mautrix remote appservice WebSocket proxy";
      wantedBy = [ "multi-user.target" ];
      after = [ "sops-nix.service" ];
      serviceConfig = {
        User = "mautrix-wsproxy";
        Group = "matrix-bridges";
        Environment = [
          "LISTEN_ADDRESS=127.0.0.1:${toString imessageWsproxyPort}"
          "APPSERVICE_ID=imessage"
        ];
        EnvironmentFile = config.sops.templates."matrix-imessage.env".path;
        ExecStart = "${imessageWsproxyPackage}/bin/mautrix-wsproxy -config env";
        Restart = "on-failure";
        RestartSec = "5s";
        UMask = "0077";
        CapabilityBoundingSet = [ "" ];
        LockPersonality = true;
        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateTmp = true;
        ProtectClock = true;
        ProtectControlGroups = true;
        ProtectHome = true;
        ProtectHostname = true;
        ProtectKernelLogs = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
        ];
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [ "@system-service" ];
      };
    };

    systemd.services.matrix-synapse = {
      requires = [ "mautrix-wsproxy.service" ];
      after = [ "mautrix-wsproxy.service" ];
    };

    homelab.routes.matrix = {
      enable = true;
      host = "matrix";
      visibility = "internal";
      upstream = "http://127.0.0.1:8008";
      description = "Private Matrix client API";
      extraConfig = ''
        @imessageAppserviceWebsocket path /_matrix/client/unstable/fi.mau.as_sync
        reverse_proxy @imessageAppserviceWebsocket http://127.0.0.1:${toString imessageWsproxyPort}
      '';
    };

    homelab.routes.chat = {
      enable = true;
      host = "chat";
      visibility = "internal";
      root = toString cinnyWeb;
      description = "Private Cinny Matrix client";
      extraConfig = ''
        @cinnyRuntimeConfig path / /index.html /config.json /manifest.json /sw.js
        header @cinnyRuntimeConfig Cache-Control "no-store"
        header {
          Content-Security-Policy "frame-ancestors 'self'"
          Permissions-Policy "camera=(self), microphone=(self), geolocation=()"
          Referrer-Policy "no-referrer"
          X-Content-Type-Options "nosniff"
          X-Frame-Options "SAMEORIGIN"
        }
      '';
    };

    assertions = [
      {
        assertion = cfg.secrets.enable;
        message = "homelab.matrix.enable requires homelab.secrets.enable for bridge credentials.";
      }
      {
        assertion = cfg.acme.enable;
        message = "homelab.matrix.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
