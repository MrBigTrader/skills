import os
import sys
import yaml
import shutil
import subprocess
from pathlib import Path

# Configurações de diretórios de busca
HOME_DIR = Path.home()
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", HOME_DIR / "AppData" / "Local"))
GLOBAL_SKILLS_DIR = Path(
    os.environ.get("GEMINI_SKILLS_DIR", HOME_DIR / ".gemini" / "config" / "skills")
)
GLOBAL_PLUGINS_DIR = Path(
    os.environ.get("GEMINI_PLUGINS_DIR", HOME_DIR / ".gemini" / "config" / "plugins")
)
PROJECTS_DIR = Path(r"c:\projetos")
HERMES_SKILLS_DIR = Path(
    os.environ.get("HERMES_SKILLS_DIR", LOCAL_APP_DATA / "hermes" / "skills")
)

# Pasta do repositório de destino
REPO_DIR = Path(__file__).resolve().parent
DEST_SKILLS_DIR = REPO_DIR / "skills"

def parse_skill_metadata(skill_md_path: Path) -> dict:
    """Faz o parse do frontmatter YAML do SKILL.md para obter nome e descrição."""
    if not skill_md_path.exists():
        return {}
        
    try:
        with open(skill_md_path, encoding="utf-8") as f:
            content = f.read()
            
        # Verifica se tem o delimitador do frontmatter YAML
        if content.startswith("---"):
            end_idx = content.find("---", 3)
            if end_idx != -1:
                yaml_content = content[3:end_idx]
                data = yaml.safe_load(yaml_content)
                if isinstance(data, dict):
                    return {
                        "name": data.get("name", skill_md_path.parent.name),
                        "description": data.get("description", "Sem descrição."),
                    }
    except Exception as e:
        print(f"   [WARN] Falha ao ler metadados de {skill_md_path.name}: {e}", file=sys.stderr)
        
    return {"name": skill_md_path.parent.name, "description": "Sem descrição."}

def find_all_skills() -> list[dict]:
    """Varre todas as pastas configuradas buscando garras de skills válidas."""
    skills_found = []
    visited_paths = set()
    
    # 1. Varre pasta global de skills
    if GLOBAL_SKILLS_DIR.exists():
        for item in GLOBAL_SKILLS_DIR.iterdir():
            skill_md = item / "SKILL.md"
            if skill_md.exists() and item not in visited_paths:
                skills_found.append({"path": item, "source": "Global Gemini"})
                visited_paths.add(item)
                
    # 2. Varre skills globais do Hermes, que podem estar em categorias.
    if HERMES_SKILLS_DIR.exists():
        for skill_md in HERMES_SKILLS_DIR.rglob("SKILL.md"):
            item = skill_md.parent
            if item not in visited_paths:
                skills_found.append({"path": item, "source": "Global Hermes"})
                visited_paths.add(item)

    # 3. Varre pasta global de plugins buscando subpastas "skills"
    if GLOBAL_PLUGINS_DIR.exists():
        for plugin in GLOBAL_PLUGINS_DIR.iterdir():
            plugin_skills = plugin / "skills"
            if plugin_skills.exists():
                for item in plugin_skills.iterdir():
                    skill_md = item / "SKILL.md"
                    if skill_md.exists() and item not in visited_paths:
                        skills_found.append({"path": item, "source": f"Plugin: {plugin.name}"})
                        visited_paths.add(item)
            # Caso a própria pasta sob o plugin seja a skill
            skill_md = plugin / "SKILL.md"
            if skill_md.exists() and plugin not in visited_paths:
                skills_found.append({"path": plugin, "source": "Plugin Root"})
                visited_paths.add(plugin)
                
    # 4. Varre projetos locais buscando pastas ".agents/skills" ou ".skills"
    if PROJECTS_DIR.exists():
        for proj in PROJECTS_DIR.iterdir():
            # Evita entrar na própria pasta 'skills' que estamos construindo
            if proj.name.lower() == "skills":
                continue
                
            search_paths = [
                proj / ".agents" / "skills",
                proj / ".skills"
            ]
            for sp in search_paths:
                if sp.exists():
                    for item in sp.iterdir():
                        skill_md = item / "SKILL.md"
                        if skill_md.exists() and item not in visited_paths:
                            skills_found.append({"path": item, "source": f"Projeto: {proj.name}"})
                            visited_paths.add(item)
                            
    return skills_found

def sync_skills():
    print("🔍 Buscando skills no sistema...", file=sys.stderr)
    skills = find_all_skills()
    versioned_hermes_skill_md = DEST_SKILLS_DIR / "github-workflow-sergio" / "SKILL.md"
    preserved_hermes_skill_md = None
    hermes_github_workflow_found = any(
        s["source"] == "Global Hermes" and s["path"].name == "github-workflow-sergio"
        for s in skills
    )
    if not hermes_github_workflow_found and versioned_hermes_skill_md.exists():
        preserved_hermes_skill_md = versioned_hermes_skill_md.read_bytes()
        skills.append({
            "path": versioned_hermes_skill_md.parent,
            "source": "Global Hermes",
        })
    print(f"   Encontradas {len(skills)} skills válidas.\n", file=sys.stderr)
    
    # Limpa a pasta 'skills' de destino anterior e reconstrói
    if DEST_SKILLS_DIR.exists():
        shutil.rmtree(DEST_SKILLS_DIR)
    DEST_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    
    skills_meta = []
    visited_names = set()
    
    for s in skills:
        src_path = s["path"]
        skill_name = src_path.name
        skill_md = src_path / "SKILL.md"
        
        dest_path = DEST_SKILLS_DIR / skill_name
        print(f"   Copiando [{s['source']}] {skill_name}…", file=sys.stderr)
        if s["source"] == "Global Hermes" and skill_name == "github-workflow-sergio":
            if dest_path.exists():
                shutil.rmtree(dest_path)
            dest_path.mkdir(parents=True, exist_ok=True)
            dest_skill_md = dest_path / "SKILL.md"
            if preserved_hermes_skill_md is not None:
                dest_skill_md.write_bytes(preserved_hermes_skill_md)
            else:
                shutil.copy2(skill_md, dest_skill_md)
            skill_md = dest_skill_md
        else:
            # Copia a pasta da skill inteira de forma recursiva (sobrescrevendo se for duplicada)
            shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
        
        # Parse dos metadados
        meta = parse_skill_metadata(skill_md)
        meta_name = meta.get("name", skill_name)
        
        # Evita duplicar no README se já visitamos uma skill de mesmo nome
        if meta_name in visited_names:
            continue
        visited_names.add(meta_name)
        
        skills_meta.append({
            "name": meta_name,
            "description": meta.get("description", "Sem descrição."),
            "folder": skill_name,
            "source": s["source"]
        })
        
    # Ordenar por nome
    skills_meta.sort(key=lambda x: x["name"].lower())
    
    # Gerar o README.md
    generate_readme(skills_meta)
    
    # Git commit e push se configurado
    git_push_changes()

def generate_readme(skills_meta: list[dict]):
    readme_path = REPO_DIR / "README.md"
    print(f"\n📝 Atualizando README.md em {readme_path}...", file=sys.stderr)
    
    content = [
        "# Central de Skills do Gemini e Claude 🧠",
        "",
        "Este repositório armazena e sincroniza centralizadamente todas as **Agent Skills** (competências) personalizadas e automatizadas disponíveis localmente nos projetos ou globalmente na máquina.",
        "",
        "As Agent Skills estendem a capacidade do assistente de codificação (como o Gemini Antigravity ou Claude Code), permitindo que ele aprenda caminhos operacionais de engenharia, deploys e testes, mantendo a produtividade contínua entre sessões.",
        "",
        "## 🛠️ Índice de Skills Disponíveis",
        "",
        "| Skill / Nome | Descrição | Pasta | Origem de Sincronismo |",
        "| :--- | :--- | :--- | :--- |"
    ]
    
    for s in skills_meta:
        link_pasta = f"[./skills/{s['folder']}](./skills/{s['folder']})"
        content.append(f"| **{s['name']}** | {s['description'].strip()} | {link_pasta} | {s['source']} |")
        
    content.extend([
        "",
        "---",
        "",
        "## 🔄 Como Sincronizar",
        "Para coletar novas skills criadas localmente nos projetos ou no diretório AppData global e atualizar este repositório no GitHub, basta executar o script localmente:",
        "```powershell",
        "python sync_skills.py",
        "```",
        "*(O script atualizará este README, copiará os arquivos e dará o push automático de volta para o GitHub).* "
    ])
    
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    print("   README.md atualizado com sucesso!", file=sys.stderr)

def git_push_changes():
    # Verifica se a pasta é um repositório git
    git_dir = REPO_DIR / ".git"
    if not git_dir.exists():
        print("\n⚠️  Diretório não é um repositório Git local. Pulando push automático.", file=sys.stderr)
        print("   Para ativar o push automático, execute: git init e conecte ao seu GitHub.", file=sys.stderr)
        return
        
    try:
        # Verifica se existe um remote configurado
        remote_check = subprocess.run(["git", "remote"], cwd=str(REPO_DIR), capture_output=True, text=True)
        if not remote_check.stdout.strip():
            print("\n⚠️  Nenhum repositório remoto (remote origin) configurado no Git. Pulando push automático.", file=sys.stderr)
            return
            
        print("\n⚡ Git: Staging, Committing e Pushing para o GitHub...", file=sys.stderr)
        subprocess.run(["git", "add", "."], cwd=str(REPO_DIR))
        
        # Commita se houver alterações
        diff_check = subprocess.run(["git", "diff", "--quiet"], cwd=str(REPO_DIR))
        diff_staged_check = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=str(REPO_DIR))
        
        if diff_check.returncode != 0 or diff_staged_check.returncode != 0:
            subprocess.run(["git", "commit", "-m", "chore: auto-sync skills database and README"], cwd=str(REPO_DIR))
            subprocess.run(["git", "push"], cwd=str(REPO_DIR))
            print("   GitHub atualizado com sucesso!", file=sys.stderr)
        else:
            print("   Nenhuma alteração detectada. Repositório já está atualizado.", file=sys.stderr)
            
    except Exception as e:
        print(f"   [WARN] Falha ao executar operações do Git: {e}", file=sys.stderr)

if __name__ == "__main__":
    sync_skills()
