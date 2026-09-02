#!/usr/bin/env ruby
# extract_strings.rb — extrae texto traducible del juego a archivos TOML
# Uso: ruby Tools/extract_strings.rb [/ruta/al/juego]
#
# Genera translation/*.toml con todos los textos listos para traducir.
# Los archivos TOML son idempotentes: si ya existen, solo agrega entradas nuevas.

require 'zlib'
require 'digest'
require 'fileutils'
require 'set'

GAME_DIR    = ARGV[0] || File.expand_path("..", __dir__)
TRANS_DIR   = File.join(GAME_DIR, "translation")
DATA_DIR    = File.join(GAME_DIR, "Data")
PBS_DIR     = File.join(GAME_DIR, "PBS")

FileUtils.mkdir_p(TRANS_DIR)

# ─────────────────────────────────────────────────────────────────────────────
# Stubs mínimos para cargar Map*.rxdata sin el motor RGSS
# ─────────────────────────────────────────────────────────────────────────────
module RPG
  class Map
    attr_accessor :events, :tileset_id, :width, :height, :autoplay_bgm,
                  :bgm, :autoplay_bgs, :bgs, :encounter_list,
                  :encounter_step, :data, :note
    def initialize; @events = {}; end
  end
  class Event
    attr_accessor :id, :name, :x, :y, :pages
    class Page
      attr_accessor :condition, :graphic, :move_type, :move_speed,
                    :move_frequency, :move_route, :walk_anime, :step_anime,
                    :direction_fix, :through, :always_on_top, :trigger, :list
      def initialize; @list = []; end
      class Condition
        attr_accessor :switch1_valid, :switch2_valid, :variable_valid,
                      :self_switch_valid, :switch1_id, :switch2_id,
                      :variable_id, :variable_value, :self_switch_ch
      end
      class Graphic
        attr_accessor :tile_id, :character_name, :character_hue, :direction,
                      :pattern, :opacity, :blend_type
      end
    end
  end
  class EventCommand
    attr_accessor :code, :indent, :parameters
    def initialize(code=0, indent=0, params=[])
      @code = code; @indent = indent; @parameters = params
    end
  end
  class CommonEvent
    attr_accessor :id, :name, :trigger, :condition, :list
    def initialize; @list = []; end
  end
  class MapInfo
    attr_accessor :name, :parent_id, :order, :expanded, :scroll_x, :scroll_y
  end
  class AudioFile
    attr_accessor :name, :volume, :pitch
  end
  class MoveRoute
    attr_accessor :repeat, :skippable, :list
  end
  class MoveCommand
    attr_accessor :code, :parameters
  end
end

# Clases auxiliares del motor RPG Maker XP
class Table
  def self._load(data) allocate.tap { |o| o.instance_variable_set(:@data, data) }; end
  def _dump(limit) @data || ""; end
end
class Color
  def self._load(data) allocate; end
  def _dump(limit) "\x00" * 32; end
  def initialize(*a); end
end
class Tone
  def self._load(data) allocate; end
  def _dump(limit) "\x00" * 32; end
  def initialize(*a); end
end

# ─────────────────────────────────────────────────────────────────────────────
# Utilidades TOML
# ─────────────────────────────────────────────────────────────────────────────
def safe_utf8(s)
  s = s.to_s
  # Ya es UTF-8 válido — retornar tal cual
  if s.encoding == Encoding::UTF_8
    return s if s.valid_encoding?
    return s.encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")
  end
  # Si es ASCII-8BIT, intentar interpretar como UTF-8 primero
  as_utf8 = s.dup.force_encoding("UTF-8")
  return as_utf8 if as_utf8.valid_encoding?
  # Fallback: asumir CP1252 (Windows Western European, típico en RPG Maker XP)
  s.dup.force_encoding("Windows-1252").encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")
rescue
  s.to_s.encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")
end

def toml_str(s)
  s = safe_utf8(s)
  if s.include?("\n")
    inner = s.gsub("\\", "\\\\").gsub('"', '\\"')
    "\"\"\"\n#{inner}\"\"\""
  else
    "\"#{s.gsub("\\", "\\\\").gsub('"', '\\"')}\""
  end
end

def entry_to_toml(e)
  lines = ["[[entry]]"]
  e.each do |k, v|
    val = v.is_a?(Integer) ? v.to_s : toml_str(safe_utf8(v))
    lines << "#{k} = #{val}"
  end
  lines.join("\n") + "\n\n"
end

def write_toml(path, header, entries)
  existing_ids = Set.new
  if File.exist?(path)
    File.read(path, encoding: "UTF-8").scan(/^id\s*=\s*"([^"]+)"/).each { |m| existing_ids << m[0] }
  end

  new_entries = entries.reject { |e| existing_ids.include?(e[:id]) }
  return 0 if new_entries.empty?

  File.open(path, "a", encoding: "UTF-8") do |f|
    if File.size(path) == 0
      f.puts "# #{header}"
      f.puts "# Generado por extract_strings.rb"
      f.puts "# original = texto fuente | translated = dejar vacío para no traducir"
      f.puts
    end
    new_entries.each { |e| f.write(entry_to_toml(e)) }
  end
  new_entries.size
end

def short_id(text)
  Digest::MD5.hexdigest(text.encode("UTF-8", invalid: :replace, undef: :replace))[0, 12]
end

# ─────────────────────────────────────────────────────────────────────────────
# Preprocesador de códigos de formato
#
# Separa el texto en tres partes:
#   prefix  — decoradores al inicio (\b, \r) — se reinyectan antes del texto
#   codes   — markers semánticos ([JUGADOR], [1], etc.) con su mapeo de vuelta
#   clean   — texto limpio que la IA puede traducir sin confusión
#
# Los códigos visuales (\c[N], <b>, <i>, etc.) se eliminan — son cosméticos.
# ─────────────────────────────────────────────────────────────────────────────
PREFIX_RE = /\A((?:\\[br])+)/

FIXED_SEMANTIC_CODES = [
  [/\\PN/,  "[JUGADOR]",    "\\PN"],
  [/\\TN/,  "[ENTRENADOR]", "\\TN"],
  [/\\GT/,  "[GT]",         "\\GT"],
  [/\\GY/,  "[GY]",         "\\GY"],
  [/<br>/,  "[BR]",         "<br>"],
].freeze

# Elimina códigos puramente visuales (color, negrita, cursiva, alineación)
VISUAL_STRIP_RE = /\\c\[\d+\]|<[bir]>|<a[clr]>|\\[br]/

def preprocess_codes(raw)
  t = safe_utf8(raw).dup
  prefix = +""

  # 1. Capturar decoradores al inicio del string
  if (m = t.match(PREFIX_RE))
    prefix = m[1]
    t = t[prefix.length..]
  end

  # 2. Eliminar códigos visuales restantes
  t.gsub!(VISUAL_STRIP_RE, "")

  # 3. Reemplazar códigos semánticos con markers legibles
  codes = {}

  FIXED_SEMANTIC_CODES.each do |pattern, marker, original_code|
    t.gsub!(pattern) { codes[marker] ||= original_code; marker }
  end

  # {N} / {N:format} → [N]
  t.gsub!(/\{(\d+)(?::[^}]*)?\}/) do
    n = $1; orig = $&; marker = "[#{n}]"
    codes[marker] ||= orig
    marker
  end

  # \v[N] → [VN]
  t.gsub!(/\\v\[(\d+)\]/) do
    n = $1; orig = $&; marker = "[V#{n}]"
    codes[marker] ||= orig
    marker
  end

  codes_str = codes.map { |k, v| "#{k}=#{v}" }.join("|")
  { clean: t, prefix: prefix, codes: codes_str }
end

def build_entry(base_fields, raw_original)
  pp = preprocess_codes(raw_original)
  e = base_fields.dup
  e[:prefix]     = pp[:prefix] unless pp[:prefix].empty?
  e[:codes]      = pp[:codes]  unless pp[:codes].empty?
  e[:original]   = pp[:clean]
  e[:translated] = ""
  e
end

# ─────────────────────────────────────────────────────────────────────────────
# 1. messages_game.dat y messages_core.dat
# ─────────────────────────────────────────────────────────────────────────────
# Secciones a traducir (índice 0-based en el Array raíz):
#   data[0] = Array de sub-Hashes con todo el texto que pasa por _INTL()
#   data[N] = Hashes indexados por ID (descripciones, mensajes de batalla, UI)
TRANSLATE_IDX_GAME = [3, 6, 9, 11, 15, 16, 17, 22, 23, 24, 26].freeze
TRANSLATE_IDX_CORE = [3, 6, 9, 11, 24, 26].freeze

# Etiquetas descriptivas por índice para el campo "context" en el TOML
SECTION_LABELS_GAME = {
  0  => "Texto _INTL() — diálogo/UI",
  3  => "Pokédex",
  6  => "Descripciones de movimientos",
  9  => "Descripciones de items",
  11 => "Descripciones de habilidades",
  15 => "Mensajes de derrota (entrenador)",
  16 => "Mensajes de victoria (entrenador)",
  17 => "Mensajes post-batalla",
  22 => "Diálogos de teléfono",
  23 => "Frases de batalla",
  24 => "Strings de UI",
  26 => "Descripciones de cintas",
}.freeze

SECTION_LABELS_CORE = {
  3  => "Pokédex (estándar)",
  6  => "Descripciones de movimientos (estándar)",
  9  => "Descripciones de items (estándar)",
  11 => "Descripciones de habilidades (estándar)",
  24 => "UI del motor PE21.1",
  26 => "Descripciones de cintas (estándar)",
}.freeze

# Strings que no deben extraerse para traducción:
#   - Rutas de archivos del juego (Graphics/, Audio/, Data/, etc.)
#   - Strings sin letras reales (IDs, números, símbolos puros)
#   - Strings muy cortos de un solo carácter
ASSET_PATH_RE = /\A(Graphics|Audio|Data|Fonts|Plugins|PBS|Animations|Battlers|
                     Characters|Icons|Panoramas|Pictures|Tilesets|Titles|
                     Transitions|Windowskins|Battler|Sprite|Script)\//xi.freeze

def not_translatable?(str)
  # Rutas de assets del motor RPG Maker / PE21.1
  return true if str =~ ASSET_PATH_RE
  # Sin ninguna letra del alfabeto → símbolo puro, ID técnico
  return true unless str =~ /[[:alpha:]]/
  false
end

def extract_messages_dat(path, translate_idx, labels, tag)
  return [] unless File.exist?(path)
  data = Marshal.load(File.binread(path))
  entries = []
  seen = Set.new

  # data[0] es Array de sub-Hashes con texto _INTL — solo en messages_game.dat
  if data[0].is_a?(Array) && !data[0].empty? && data[0].first.is_a?(Hash) && !data[0].first.empty?
    label = labels[0] || "Texto _INTL()"
    data[0].each do |bucket|
      next unless bucket.is_a?(Hash)
      bucket.each_key do |original|
        next unless original.is_a?(String) && original.length >= 5
        next if seen.include?(original)
        next if not_translatable?(original)
        seen << original
        entries << build_entry(
          { id: "#{tag}_d0_#{short_id(original)}", section: 0, context: label },
          original
        )
      end
    end
  end

  # data[N] — Hashes indexados por ID de game data
  translate_idx.each do |idx|
    sec = data[idx]
    next unless sec.is_a?(Hash) && !sec.empty?
    label = labels[idx] || "Sección #{idx}"
    sec.each_key do |original|
      next unless original.is_a?(String) && original.length >= 5
      next if seen.include?(original)
      next if not_translatable?(original)
      seen << original
      entries << build_entry(
        { id: "#{tag}_s#{idx}_#{short_id(original)}", section: idx, context: label },
        original
      )
    end
  end

  entries
rescue => e
  warn "  Error leyendo #{File.basename(path)}: #{e.message}"
  []
end

puts "=== Extrayendo messages_game.dat ==="
game_entries = extract_messages_dat(
  File.join(DATA_DIR, "messages_game.dat"),
  TRANSLATE_IDX_GAME, SECTION_LABELS_GAME, "g"
)
n = write_toml(
  File.join(TRANS_DIR, "messages_game.toml"),
  "Textos del juego — messages_game.dat",
  game_entries
)
puts "  #{n} entradas nuevas → messages_game.toml (#{game_entries.size} extraídas)"

puts "=== Extrayendo messages_core.dat ==="
core_entries = extract_messages_dat(
  File.join(DATA_DIR, "messages_core.dat"),
  TRANSLATE_IDX_CORE, SECTION_LABELS_CORE, "c"
)
n = write_toml(
  File.join(TRANS_DIR, "messages_core.toml"),
  "Textos del motor PE21.1 — messages_core.dat",
  core_entries
)
puts "  #{n} entradas nuevas → messages_core.toml (#{core_entries.size} extraídas)"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Map*.rxdata — diálogo de NPCs
# ─────────────────────────────────────────────────────────────────────────────
def flush_map_buffer(buffer, buf_lines, entries)
  return unless buffer
  joined = buf_lines.join("\n")
  return if joined.strip.empty?
  pp = preprocess_codes(joined)
  buffer[:original] = pp[:clean]
  buffer[:prefix]   = pp[:prefix] unless pp[:prefix].empty?
  buffer[:codes]    = pp[:codes]  unless pp[:codes].empty?
  entries << buffer
end

def extract_map_events(map_path, map_id, map_name)
  map = Marshal.load(File.binread(map_path))
  entries = []
  map.events.each do |eid, event|
    event.pages.each_with_index do |page, page_idx|
      buffer = nil; buf_lines = []
      page.list.each_with_index do |cmd, cmd_idx|
        case cmd.code
        when 101
          flush_map_buffer(buffer, buf_lines, entries)
          ename = safe_utf8(event.respond_to?(:name) ? event.name.to_s : "")
          mname = safe_utf8(map_name)
          buffer = {
            id:      "M#{map_id}E#{eid}P#{page_idx}C#{cmd_idx}",
            map:     map_id,
            event:   eid,
            page:    page_idx,
            cmd:     cmd_idx,
            context: "#{mname} | #{ename} | Pag.#{page_idx}",
          }
          buf_lines = [safe_utf8(cmd.parameters[0])]
        when 401
          buf_lines << safe_utf8(cmd.parameters[0]) if buffer
        else
          flush_map_buffer(buffer, buf_lines, entries)
          buffer = nil; buf_lines = []
        end
      end
      flush_map_buffer(buffer, buf_lines, entries)
    end
  end
  entries
rescue => e
  warn "  Error en mapa #{map_id}: #{e.message}"
  []
end

puts "=== Extrayendo Map*.rxdata ==="
map_infos = {}
map_info_path = File.join(DATA_DIR, "MapInfos.rxdata")
if File.exist?(map_info_path)
  Marshal.load(File.binread(map_info_path)).each { |id, info| map_infos[id] = info.name rescue id.to_s }
end

map_entries = []
Dir.glob(File.join(DATA_DIR, "Map[0-9]*.rxdata")).sort.each do |path|
  id = File.basename(path)[/\d+/].to_i
  name = map_infos[id] || "Map#{id}"
  map_entries.concat(extract_map_events(path, id, name))
end

n = write_toml(
  File.join(TRANS_DIR, "maps.toml"),
  "Diálogos de NPCs — Map*.rxdata",
  map_entries
)
puts "  #{n} entradas nuevas → maps.toml (#{map_entries.size} extraídas de #{Dir.glob(File.join(DATA_DIR, 'Map[0-9]*.rxdata')).size} mapas)"

# ─────────────────────────────────────────────────────────────────────────────
# 3. CommonEvents.rxdata
# ─────────────────────────────────────────────────────────────────────────────
def extract_common_events(path)
  entries = []
  data = Marshal.load(File.binread(path))
  data.each do |event|
    next unless event && event.respond_to?(:list) && event.list
    name = event.respond_to?(:name) ? event.name.to_s : "CE#{event.id}"
    buffer = nil; buf_lines = []
    event.list.each_with_index do |cmd, cmd_idx|
      case cmd.code
      when 101
        flush_map_buffer(buffer, buf_lines, entries)
        buffer = {
          id:      "CE#{event.id}C#{cmd_idx}",
          event:   event.id,
          cmd:     cmd_idx,
          context: "CommonEvent: #{name}",
        }
        buf_lines = [cmd.parameters[0].to_s]
      when 401
        buf_lines << cmd.parameters[0].to_s if buffer
      else
        flush_map_buffer(buffer, buf_lines, entries)
        buffer = nil; buf_lines = []
      end
    end
    flush_map_buffer(buffer, buf_lines, entries)
  end
  entries
rescue => e
  warn "  Error en CommonEvents: #{e.message}"
  []
end

puts "=== Extrayendo CommonEvents.rxdata ==="
ce_path = File.join(DATA_DIR, "CommonEvents.rxdata")
ce_entries = extract_common_events(ce_path)
n = write_toml(
  File.join(TRANS_DIR, "common_events.toml"),
  "Diálogos de eventos comunes — CommonEvents.rxdata",
  ce_entries
)
puts "  #{n} entradas nuevas → common_events.toml (#{ce_entries.size} extraídas)"

# ─────────────────────────────────────────────────────────────────────────────
# 4. Archivos PBS (texto plano)
# ─────────────────────────────────────────────────────────────────────────────
PBS_CONFIG = {
  "pokemon.txt"           => %w[Pokedex],
  "moves.txt"             => %w[Description],
  "moves_Gen_9_Pack.txt"  => %w[Description],
  "abilities.txt"         => %w[Description],
  "items.txt"             => %w[Description],
  "items_Gen_9_Pack.txt"  => %w[Description],
  "ribbons.txt"           => %w[Description],
  "trainers.txt"          => %w[LoseText],
  "phone.txt"             => %w[Text],
}.freeze

def extract_pbs_file(path, fields)
  return [] unless File.exist?(path)
  entries = []; current_id = nil
  File.foreach(path, encoding: "UTF-8") do |raw|
    line = raw.encode("UTF-8", invalid: :replace, undef: :replace).chomp
    next if line.start_with?("#") || line.strip.empty?
    if line =~ /^\[([^\]]+)\]$/
      current_id = $1.strip
    elsif current_id && line =~ /^(\w+)\s*=\s*(.+)$/
      field = $1.strip; value = $2.strip
      next unless fields.include?(field)
      next if value.length < 3
      entries << {
        id:      "pbs:#{File.basename(path)}:#{current_id}:#{field}",
        file:    File.basename(path),
        pbs_id:  current_id,
        field:   field,
        original:   value,
        translated: "",
      }
    end
  end
  entries
rescue => e
  warn "  Error en PBS #{File.basename(path)}: #{e.message}"
  []
end

puts "=== Extrayendo archivos PBS ==="
pbs_entries = []
PBS_CONFIG.each do |filename, fields|
  path = File.join(PBS_DIR, filename)
  next unless File.exist?(path)
  es = extract_pbs_file(path, fields)
  pbs_entries.concat(es)
  puts "  #{File.basename(path)}: #{es.size} entradas"
end
n = write_toml(
  File.join(TRANS_DIR, "pbs.toml"),
  "Descripciones PBS (pokemon.txt, moves.txt, abilities.txt…)",
  pbs_entries
)
puts "  #{n} entradas nuevas → pbs.toml"

# ─────────────────────────────────────────────────────────────────────────────
# 5. Scripts.rxdata — strings hardcodeados en scripts de Ruby
# ─────────────────────────────────────────────────────────────────────────────
TARGET_SCRIPTS_NAMES = %w[PlayerBreeding PlayerPokemonPregnancy HornyStatus].freeze
# Patrón: pbMessage("...") o pbMessage('...')
PBMESSAGE_RE = /pbMessage\(\s*["']((?:[^"'\\]|\\.)*?)["']\s*\)/

def extract_script_strings(scripts_path, target_names)
  return [] unless File.exist?(scripts_path)
  entries = []
  data = Marshal.load(File.binread(scripts_path))
  data.each do |entry|
    script_name = entry[1].to_s rescue next
    next unless target_names.any? { |t| script_name.include?(t) }
    begin
      code = Zlib::Inflate.inflate(entry[2])
      idx = 0
      code.scan(PBMESSAGE_RE) do |match|
        text = match[0].gsub(/\\n/, "\n").gsub(/\\t/, "\t")
                       .gsub(/\\"/, '"').gsub(/\\'/, "'")
        next if text.strip.length < 4
        entries << {
          id:      "scr:#{script_name}:#{short_id(text)}",
          script:  script_name,
          original:   text,
          translated: "",
        }
        idx += 1
      end
    rescue => e
      warn "  Error descomprimiendo #{script_name}: #{e.message}"
    end
  end
  entries
rescue => e
  warn "  Error en Scripts.rxdata: #{e.message}"
  []
end

puts "=== Extrayendo Scripts.rxdata (strings hardcodeados) ==="
script_entries = extract_script_strings(
  File.join(DATA_DIR, "Scripts.rxdata"),
  TARGET_SCRIPTS_NAMES
)
n = write_toml(
  File.join(TRANS_DIR, "scripts.toml"),
  "Strings hardcodeados en scripts Ruby (PlayerBreeding, etc.)",
  script_entries
)
puts "  #{n} entradas nuevas → scripts.toml (#{script_entries.size} extraídas)"

# ─────────────────────────────────────────────────────────────────────────────
# Resumen final
# ─────────────────────────────────────────────────────────────────────────────
total = game_entries.size + core_entries.size + map_entries.size +
        ce_entries.size + pbs_entries.size + script_entries.size
puts
puts "━━━ Extracción completa ━━━"
puts "  messages_game.toml  : #{game_entries.size}"
puts "  messages_core.toml  : #{core_entries.size}"
puts "  maps.toml           : #{map_entries.size}"
puts "  common_events.toml  : #{ce_entries.size}"
puts "  pbs.toml            : #{pbs_entries.size}"
puts "  scripts.toml        : #{script_entries.size}"
puts "  ─────────────────────────"
puts "  TOTAL               : #{total}"
puts "  Directorio: #{TRANS_DIR}"
