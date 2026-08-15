{ pkgs }:

let
  python = pkgs.python3.override {
    packageOverrides =
      final: _prev:
      let
        wheel =
          {
            pname,
            version,
            url,
            sha256,
            dependencies ? [ ],
            nativeBuildInputs ? [ ],
            buildInputs ? [ ],
            makeWrapperArgs ? [ ],
          }:
          final.buildPythonPackage {
            inherit
              pname
              version
              dependencies
              nativeBuildInputs
              buildInputs
              makeWrapperArgs
              ;
            format = "wheel";
            src = pkgs.fetchurl { inherit url sha256; };
            doCheck = false;
          };
      in
      {
        "agent-client-protocol" = wheel {
          pname = "agent-client-protocol";
          version = "0.11.1";
          url = "https://files.pythonhosted.org/packages/18/28/cc93079c418b03de7a778cabbf66ceac5add98592f5daf30cf6f4b8f9096/agent_client_protocol-0.11.1-py3-none-any.whl";
          sha256 = "42790f0a25b8fd24f5c9b27b7e0c34123fc1a980024ad8ef965d1d169a5e42d4";
          dependencies = [ final.pydantic ];
        };

        "jupyter-ai" = wheel {
          pname = "jupyter-ai";
          version = "3.1.3";
          url = "https://files.pythonhosted.org/packages/c7/fc/8cc594a1514e70dcd787b764ea4af9ca1571dd1d85c679d41177e626f9f4/jupyter_ai-3.1.3-py3-none-any.whl";
          sha256 = "0206bc9b63de7f157852b0771c8ddb7769e823943613117e268c21d7bca2917b";
          dependencies = with final; [
            jupyter-ai-acp-client
            jupyter-ai-chat-commands
            jupyter-ai-persona-manager
            jupyter-ai-router
            jupyter-ai-tools
            jupyter-server-documents
            jupyter-server-mcp
            jupyterlab-chat
            jupyterlab-commands-toolkit
            jupyterlab-notebook-awareness
          ];
        };

        "jupyter-ai-acp-client" = wheel {
          pname = "jupyter-ai-acp-client";
          version = "0.2.1";
          url = "https://files.pythonhosted.org/packages/a2/8a/9b898f49cf519265530f278de2d91e4ad883eb00ccf875b0a8719d7cc9a7/jupyter_ai_acp_client-0.2.1-py3-none-any.whl";
          sha256 = "a15b005a711399fc89ab07e6607de987a3fc00b5dc79d75e8d2c1bd8efacc574";
          dependencies = with final; [
            agent-client-protocol
            jupyter-ai-persona-manager
            jupyter-server
            jupyterlab-chat
            pydantic
          ];
        };

        "jupyter-ai-chat-commands" = wheel {
          pname = "jupyter-ai-chat-commands";
          version = "0.0.4";
          url = "https://files.pythonhosted.org/packages/e3/b9/08f75e5133cc4aada0d324dfdd6aba8437627b580848288d47be15f016cc/jupyter_ai_chat_commands-0.0.4-py3-none-any.whl";
          sha256 = "5f8ca69ae3e3c07f911b64219673ec2a2ddffc1e93e04d8ccdb79bb792503ab5";
          dependencies = with final; [
            jupyter-ai-persona-manager
            jupyter-ai-router
            jupyter-server
            jupyterlab-chat
          ];
        };

        "jupyter-ai-persona-manager" = wheel {
          pname = "jupyter-ai-persona-manager";
          version = "0.1.2";
          url = "https://files.pythonhosted.org/packages/09/de/369982bf8993916f9feb499a7a1bfa64c316333d4c81297d3f9a1fab0b52/jupyter_ai_persona_manager-0.1.2-py3-none-any.whl";
          sha256 = "da06be8301393daf94b46506607f90f16314a43d7aceebc85ca932950b6e13aa";
          dependencies = with final; [
            importlib-metadata
            jupyter-ai-router
            jupyter-server-fileid
            jupyter-server
            jupyterlab-chat
            pycrdt
            pydantic
          ];
        };

        "jupyter-ai-router" = wheel {
          pname = "jupyter-ai-router";
          version = "0.0.7";
          url = "https://files.pythonhosted.org/packages/3f/aa/2489ba95dbc6d7e5ad0d8fa7babf9c01b7251ca555438beaa99fc9df9482/jupyter_ai_router-0.0.7-py3-none-any.whl";
          sha256 = "2b1b9a98ddd1fdfcf7a00d0582e19d1177fdb3f977654cabd03776a45aed2e2a";
          dependencies = with final; [
            jupyter-server
            jupyterlab-chat
          ];
        };

        "jupyter-ai-tools" = wheel {
          pname = "jupyter-ai-tools";
          version = "0.6.1";
          url = "https://files.pythonhosted.org/packages/7e/85/09d8eacdeec6d41284ff5d5d9f1f2e196c02a1e7340d56438863eb86d4d6/jupyter_ai_tools-0.6.1-py3-none-any.whl";
          sha256 = "c7de5593586c15bb1dbe73f28cf1fb41877a8952e8bb9d00231c15832eaf7a45";
          dependencies = with final; [
            jupyter-server
            jupyter-ydoc
            pycrdt
          ];
        };

        "jupyter-server-documents" = wheel {
          pname = "jupyter-server-documents";
          version = "0.3.3";
          url = "https://files.pythonhosted.org/packages/26/6b/bbdf93a5f1b0f4067a42799dd88eda7ad55ff799a20b2590a6ba75ee16e8/jupyter_server_documents-0.3.3-py3-none-any.whl";
          sha256 = "af4d0068fe7b29fc90f6e8dc53d4b861b99fa7f310bf4535c63a5a6a08407930";
          dependencies = with final; [
            jupyter-collaboration-ui
            jupyter-docprovider
            jupyter-server-fileid
            jupyter-server
            jupyter-ydoc
            pycrdt
          ];
        };

        "jupyter-server-mcp" = wheel {
          pname = "jupyter-server-mcp";
          version = "0.2.1";
          url = "https://files.pythonhosted.org/packages/7b/ce/a31c028e5f388c1ab9e0772af0c24d46799b73c8745c41b076c7afdfdce3/jupyter_server_mcp-0.2.1-py3-none-any.whl";
          sha256 = "2e118d7c43eb6e6bb316837d87dd9ec2d1430fdb1e8364559e7a26e165579c85";
          dependencies = with final; [
            fastmcp
            jupyter-server
          ];
        };

        "jupyterlab-chat" = wheel {
          pname = "jupyterlab-chat";
          version = "0.23.2";
          url = "https://files.pythonhosted.org/packages/14/85/ec921f11bf18a9df1d9001bb6c7ba1ca3b712d11985c7ad444f9ff4540f2/jupyterlab_chat-0.23.2-py3-none-any.whl";
          sha256 = "27dbc5de03b1723e682d4546c377181bdcec54819b8abc9b59d8b17adc4e1df8";
          dependencies = with final; [
            jupyter-collaboration
            jupyter-server
            jupyter-ydoc
            pycrdt
          ];
        };

        "jupyterlab-commands-toolkit" = wheel {
          pname = "jupyterlab-commands-toolkit";
          version = "0.1.6";
          url = "https://files.pythonhosted.org/packages/fa/a4/8020b94a839ead57e2f82eaf29003b826ece4b3847380b159ac8ea083c1b/jupyterlab_commands_toolkit-0.1.6-py3-none-any.whl";
          sha256 = "2a4a917d3dd352d21df16692346c19166ed4bd42e95ac3d2e028377308033b71";
          dependencies = with final; [
            jupyter-server
            jupyterlab-eventlistener
          ];
        };

        "jupyterlab-notebook-awareness" = wheel {
          pname = "jupyterlab-notebook-awareness";
          version = "0.2.0";
          url = "https://files.pythonhosted.org/packages/3d/b9/f54616ace9225c7688e2076f9f7c64bddd8e221405e581dd44c798573327/jupyterlab_notebook_awareness-0.2.0-py3-none-any.whl";
          sha256 = "c761718b21648bc31ea5b7c38585d0a3ad0f4a5bde9d7feadaaaba301bc276a3";
        };

        "jupyter-collaboration" = wheel {
          pname = "jupyter-collaboration";
          version = "5.0.0";
          url = "https://files.pythonhosted.org/packages/b9/a4/e848f7610e0deb51057bda248e4055ba80d1c22de7824b8f98191cd24374/jupyter_collaboration-5.0.0-py3-none-any.whl";
          sha256 = "66896e86ff3b5d1120766d6f52aa89fd7405a1841eaf0fa6f93eb8d5db61fb73";
          dependencies = with final; [
            jupyter-collaboration-ui
            jupyter-docprovider
            jupyter-server-ydoc
            jupyterlab
          ];
        };

        "jupyter-collaboration-ui" = wheel {
          pname = "jupyter-collaboration-ui";
          version = "3.0.0";
          url = "https://files.pythonhosted.org/packages/1f/77/05ab9ab28ed187da410b478f6013852ed2377ad0b490b3c28b2e92f57e55/jupyter_collaboration_ui-3.0.0-py3-none-any.whl";
          sha256 = "91c850e20a510db5e2e3e25cedd3f3f8b54ae36e79a953deec890e72a9f6e688";
        };

        "jupyter-docprovider" = wheel {
          pname = "jupyter-docprovider";
          version = "3.0.0";
          url = "https://files.pythonhosted.org/packages/60/90/ed3ac5d98cb9d917399d763616f9c8ae63fe5fb07997d5aca5834f6f8ee9/jupyter_docprovider-3.0.0-py3-none-any.whl";
          sha256 = "18ef6bf947a576285ec84eedf650473cb883a24fe56c25071305dbb015100095";
        };

        "jupyter-server-ydoc" = wheel {
          pname = "jupyter-server-ydoc";
          version = "3.0.0";
          url = "https://files.pythonhosted.org/packages/99/6c/cd724c80396a3714f1e71a710a97d71ab9dd6578a4f78a2f021a07c0ff3a/jupyter_server_ydoc-3.0.0-py3-none-any.whl";
          sha256 = "95bbfda21fdfe537fdc2e1d2a5319552e620c56f0e8262a3af3e654e5b7dc205";
          dependencies = with final; [
            jsonschema
            jupyter-events
            jupyter-server-fileid
            jupyter-server
            jupyter-ydoc
            pycrdt
            pycrdt-websocket
          ];
        };

        "jupyter-ydoc" = wheel {
          pname = "jupyter-ydoc";
          version = "4.1.1";
          url = "https://files.pythonhosted.org/packages/3f/c7/b59250cfef2bd3316117401ca0aa9685fefddb0634362bea62fcb5fa84df/jupyter_ydoc-4.1.1-py3-none-any.whl";
          sha256 = "ec8e2cc29d3159ecbd899d09e9dc6646a5652df2c6b3dc1dcf5837c6acc9e425";
          dependencies = with final; [
            anyio
            pycrdt
          ];
        };

        jupyterlab = wheel {
          pname = "jupyterlab";
          version = "4.6.3";
          url = "https://files.pythonhosted.org/packages/e9/47/242f46de028074651c9bd6d8000fc340ed0d3cdd1a0eae4387826123413a/jupyterlab-4.6.3-py3-none-any.whl";
          sha256 = "0a1ebc6567186f1eabd99536e94df7ed9e96d1e7c5ddf3e4406ae16e88abacb7";
          dependencies = with final; [
            async-lru
            httpx
            ipykernel
            jinja2
            jupyter-builder
            jupyter-core
            jupyter-lsp
            jupyter-server
            jupyterlab-server
            notebook-shim
            packaging
            tornado
            traitlets
          ];
          makeWrapperArgs = [
            "--set"
            "JUPYTERLAB_DIR"
            "$out/share/jupyter/lab"
          ];
        };

        "jupyterlab-eventlistener" = wheel {
          pname = "jupyterlab-eventlistener";
          version = "0.4.0";
          url = "https://files.pythonhosted.org/packages/63/3f/b134971e57cd67fe42343ffa8d84d3c5efaed89367740028ec4db7f81f00/jupyterlab_eventlistener-0.4.0-py3-none-any.whl";
          sha256 = "7b4a1dbd602d148791692dc40a35b902734557021fce5c3d274424039f4d9620";
        };

        pycrdt = wheel {
          pname = "pycrdt";
          version = "0.14.2";
          url = "https://files.pythonhosted.org/packages/12/20/fbbfd0ef8123c9d9e5135a0428abd4a6e1e95dd4ca74af42bc4258d41a45/pycrdt-0.14.2-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl";
          sha256 = "735079be22dd7d2b2c11bbaf88f59b14c19f3d6151edf687e87fd2aacae1dd2e";
          dependencies = [ final.anyio ];
          nativeBuildInputs = [ pkgs.autoPatchelfHook ];
          buildInputs = [ pkgs.stdenv.cc.cc.lib ];
        };

        "pycrdt-store" = wheel {
          pname = "pycrdt-store";
          version = "0.1.5";
          url = "https://files.pythonhosted.org/packages/7c/65/2edb1bb1cdce06df2aa2dcf617594344b5fc7f823d0770db2647e0306010/pycrdt_store-0.1.5-py3-none-any.whl";
          sha256 = "5ef6978d363be01275ffc337567072050363fa18fd6a51f0a48917dc210025f2";
          dependencies = with final; [
            anyio
            pycrdt
            sqlite-anyio
          ];
        };

        "pycrdt-websocket" = wheel {
          pname = "pycrdt-websocket";
          version = "0.16.4";
          url = "https://files.pythonhosted.org/packages/9f/2b/3559cd224ee4153127b28138842ce436a3dca4ad82fd30054f3cddb1401c/pycrdt_websocket-0.16.4-py3-none-any.whl";
          sha256 = "5c1612ea4e8743c4eb9d46b938b9e727ddfc7aee0d20130627e0d6c1fcc083da";
          dependencies = with final; [
            anyio
            pycrdt-store
            pycrdt
          ];
        };

        "sqlite-anyio" = wheel {
          pname = "sqlite-anyio";
          version = "0.2.10";
          url = "https://files.pythonhosted.org/packages/6b/a5/fdb940b6a402d35e17fb218cffa12685fc0cef7042d33c5cfc5b6ba3f449/sqlite_anyio-0.2.10-py3-none-any.whl";
          sha256 = "059d9d401f455fcfb6283770fcd6b42f8366d21cf9f256ff56d20f7ec1141b8f";
          dependencies = with final; [
            anyio
            typing-extensions
          ];
        };

        "jupyter-server" = wheel {
          pname = "jupyter-server";
          version = "2.20.0";
          url = "https://files.pythonhosted.org/packages/f3/71/8c002223e873a870f5c41dc69b0a7c922301123e4a31d5d01ecb700aef77/jupyter_server-2.20.0-py3-none-any.whl";
          sha256 = "c3b67c93c471e947c18b5026f04f21614218adb706df8f48227d3ee8e0a7cdcc";
          dependencies = with final; [
            anyio
            argon2-cffi
            jinja2
            jupyter-client
            jupyter-core
            jupyter-events
            jupyter-server-terminals
            nbconvert
            nbformat
            packaging
            prometheus-client
            pyzmq
            send2trash
            terminado
            tornado
            traitlets
            websocket-client
          ];
        };

        "jupyter-builder" = wheel {
          pname = "jupyter-builder";
          version = "1.2.2";
          url = "https://files.pythonhosted.org/packages/c4/3b/920bc7f3c2ad25abc0071ae7ae55789f4b85ecf3e4467f0602a88dc668cb/jupyter_builder-1.2.2-py3-none-any.whl";
          sha256 = "6ebcd4c49daf5df6a18068a74a48010406700ed90a76c189fac43eaf85c60c63";
          dependencies = with final; [
            jupyter-core
            traitlets
          ];
        };
      };
  };
in
python.withPackages (pythonPackages: [
  pythonPackages.ipykernel
  pythonPackages.jupyter-ai
])
