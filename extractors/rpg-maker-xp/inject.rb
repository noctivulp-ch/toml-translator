#!/usr/bin/env ruby
# inject_strings.rb — inyecta traducciones TOML de vuelta en los archivos del juego
# Uso: ruby Tools/inject_strings.rb [/ruta/al/juego]
#
# Lee translation/*.toml, toma las entradas con translated != "" y parchea
# Data/*.dat, Data/Map*.rxdata, Data/CommonEvents.rxdata, PBS/*.txt y Data/Scripts.rxdata.
# Hace backup *.bak antes de modificar cada archivo (solo la primera vez).

require 'zlib'
require 'fileutils'

GAME_DIR  = ARGV[0] || File.expand_path("..", __dir__)
TRANS_DIR = File.join(GAME_DIR, "translation")
DATA_DIR  = File.join(GAME_DIR, "Data")
PBS_DIR   = File.join(GAME_DIR, "PBS")

# ─────────────────────────────────────────────────────────────────────────────
# Stubs RPG Maker XP (idénticos a los del extractor)
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
  end
  class CommonEvent
    attr_accessor :id, :name, :trigger, :condition, :list
    def initialize; @list = []; end
  end
  class MapInfo
    attr_accessor :name, :parent_id, :order, :expanded, :scroll_x, :scroll_y
  end
  class AudioFile; attr_accessor :name, :volume, :pitch; end
  class MoveRoute; attr_accessor :repeat, :skippable, :list; end
  class MoveCommand; attr_accessor :code, :parameters; end
end

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
# Parser TOML minimalista para nuestro formato
# ─────────────────────────────────────────────────────────────────────────────
def parse_toml(path)
  return [] unless File.exist?(path)
  entries = []
  current = nil
  in_multiline = nil
  ml_key = nil; ml_buf = []

  File.foreach(path, encoding: "UTF-8") do |raw|
    line = raw.encode("UTF-8", invalid: :replace, undef: :replace).rstrip

    # Continuar multiline
    if in_multiline
      if line.end_with?('"""')
        ml_buf << line.chomp('"""')
        current[ml_key] = ml_buf.join("\n").sub(/\A\n/, "")
        in_multiline = false; ml_key = nil; ml_buf = []
      else
        ml_buf << line
      end
      next
    end

    next if line.start_with?("#") || line.strip.empty?

    if line.strip == "[[entry]]"
      entries << current if current && current[:id]
      current = {}
      next
    end

    next unless current

    if line =~ /^(\w+)\s*=\s*"""$/
      ml_key  = $1.to_sym
      ml_buf  = []
      in_multiline = true
      next
    end

    if line =~ /^(\w+)\s*=\s*"""(.*?)"""$/
      current[$1.to_sym] = $2
      next
    end

    if line =~ /^(\w+)\s*=\s*"(.*)"$/
      key = $1.to_sym
      val = $2.gsub('\\"', '"').gsub("\\\\", "\\")
      current[key] = val
      next
    end

    if line =~ /^(\w+)\s*=\s*(-?\d+)$/
      current[$1.to_sym] = $2.to_i
      next
    end
  end
  entries << current if current && current[:id]
  entries
rescue => e
  warn "  Error parseando #{File.basename(path)}: #{e.message}"
  []
end

def load_translated(path)
  parse_toml(path).select { |e| e[:translated] && !e[:translated].empty? }
end

def backup(path)
  bak = "#{path}.bak"
  FileUtils.cp(path, bak) unless File.exist?(bak)
end

def validate_marshal(path, data)
  Marshal.load(Marshal.dump(data))
  true
rescue => e
  warn "  ADVERTENCIA: validación Marshal falló para #{File.basename(path)}: #{e.message}"
  false
end

FORMAT_CODE_RE = /(\{[0-9]+(?::[^}]*)?\}|\\c\[\d+\]|\\[A-Z]{1,2}|\\v\[\d+\]|<[a-z]+>)/

def warn_missing_codes(original, translated, id)
  orig_codes = original.scan(FORMAT_CODE_RE).flatten.sort
  trad_codes = translated.scan(FORMAT_CODE_RE).flatten.sort
  missing = orig_codes - trad_codes
  warn "  ADVERTENCIA código faltante en #{id}: #{missing.inspect}" unless missing.empty?
end

# Reconstruye el texto final a partir de campos del nuevo formato:
#   prefix   — decoradores que van al inicio (\b, \r)
#   codes    — "[JUGADOR]=\\PN|[1]={1}" — markers → códigos originales
#   text     — texto limpio con markers ([JUGADOR], [1], etc.)
#
# Backward-compatible: si prefix y codes están vacíos/nil, devuelve text sin cambios.
def reconstruct(text, prefix, codes_str)
  t = text.to_s.dup
  unless codes_str.nil? || codes_str.strip.empty?
    codes_str.split("|").each do |pair|
      k, v = pair.split("=", 2)
      next unless k && v
      t.gsub!(k, v)
    end
  end
  prefix.to_s + t
end

# Para una entry del TOML, reconstruye el texto final (original o traducido)
def reconstruct_entry(entry, field)
  reconstruct(entry[field].to_s, entry.fetch(:prefix, ""), entry.fetch(:codes, ""))
end

# ─────────────────────────────────────────────────────────────────────────────
# 1. messages_game.dat / messages_core.dat
# ─────────────────────────────────────────────────────────────────────────────
def inject_messages_dat(dat_path, entries)
  return 0 unless File.exist?(dat_path)
  return 0 if entries.empty?

  # Construir lookup: dat_key → inject_value
  # dat_key   = original completo reconstruido (con prefix y codes restaurados)
  # inject_val = traducido completo reconstruido
  lookup = {}
  entries.each do |e|
    dat_key    = reconstruct_entry(e, :original)
    inject_val = reconstruct_entry(e, :translated)
    lookup[dat_key] = inject_val
  end

  backup(dat_path)
  data = Marshal.load(File.binread(dat_path))
  count = 0

  # data[0]: Array de sub-Hashes
  if data[0].is_a?(Array)
    data[0].each do |bucket|
      next unless bucket.is_a?(Hash)
      bucket.each_key do |dat_key|
        if lookup.key?(dat_key)
          warn_missing_codes(dat_key, lookup[dat_key], "d0")
          bucket[dat_key] = lookup[dat_key]
          count += 1
        end
      end
    end
  end

  # data[1..30]: Hashes de secciones
  data.each_with_index do |sec, idx|
    next unless sec.is_a?(Hash)
    sec.each_key do |dat_key|
      if lookup.key?(dat_key)
        warn_missing_codes(dat_key, lookup[dat_key], "s#{idx}")
        sec[dat_key] = lookup[dat_key]
        count += 1
      end
    end
  end

  File.binwrite(dat_path, Marshal.dump(data))
  validate_marshal(dat_path, data)
  count
rescue => e
  warn "  Error inyectando #{File.basename(dat_path)}: #{e.message}"
  0
end

# ─────────────────────────────────────────────────────────────────────────────
# 2. Map*.rxdata — eventos de mapa
# ─────────────────────────────────────────────────────────────────────────────
def inject_maps(data_dir, map_entries)
  return 0 if map_entries.empty?

  # Agrupar entries por mapa
  by_map = map_entries.group_by { |e| e[:map] }
  total = 0

  by_map.each do |map_id, entries|
    path = File.join(data_dir, "Map#{map_id.to_s.rjust(3, '0')}.rxdata")
    next unless File.exist?(path)

    backup(path)
    map = Marshal.load(File.binread(path))
    changed = 0

    entries.each do |e|
      event  = map.events[e[:event]]
      next unless event
      page = event.pages[e[:page]]
      next unless page
      cmd_idx = e[:cmd]
      cmd = page.list[cmd_idx]
      next unless cmd && cmd.code == 101

      full_original   = reconstruct_entry(e, :original)
      full_translated = reconstruct_entry(e, :translated)
      warn_missing_codes(full_original, full_translated, e[:id])
      translated_lines = full_translated.split("\n")

      # Reemplazar primera línea (cmd 101)
      cmd.parameters[0] = translated_lines.shift || ""

      # Actualizar/crear cmds 401 que siguen
      i = cmd_idx + 1
      translated_lines.each do |tline|
        if page.list[i] && page.list[i].code == 401
          page.list[i].parameters[0] = tline
        else
          # Insertar nuevo cmd 401
          new_cmd = RPG::EventCommand.new
          new_cmd.code = 401; new_cmd.indent = cmd.indent; new_cmd.parameters = [tline]
          page.list.insert(i, new_cmd)
        end
        i += 1
      end
      # Si el original tenía más líneas 401 que la traducción, dejar las restantes vacías
      while page.list[i] && page.list[i].code == 401
        page.list[i].parameters[0] = ""
        i += 1
      end
      changed += 1
    end

    File.binwrite(path, Marshal.dump(map))
    total += changed
  end

  total
rescue => e
  warn "  Error inyectando mapas: #{e.message}"
  0
end

# ─────────────────────────────────────────────────────────────────────────────
# 3. CommonEvents.rxdata
# ─────────────────────────────────────────────────────────────────────────────
def inject_common_events(path, ce_entries)
  return 0 unless File.exist?(path) && !ce_entries.empty?

  by_event = ce_entries.group_by { |e| e[:event] }
  backup(path)
  data = Marshal.load(File.binread(path))
  total = 0

  data.each do |event|
    next unless event && event.respond_to?(:id)
    entries = by_event[event.id]
    next unless entries

    entries.each do |e|
      cmd_idx = e[:cmd]
      cmd = event.list[cmd_idx]
      next unless cmd && cmd.code == 101

      full_original   = reconstruct_entry(e, :original)
      full_translated = reconstruct_entry(e, :translated)
      warn_missing_codes(full_original, full_translated, e[:id])
      translated_lines = full_translated.split("\n")
      cmd.parameters[0] = translated_lines.shift || ""

      i = cmd_idx + 1
      translated_lines.each do |tline|
        if event.list[i] && event.list[i].code == 401
          event.list[i].parameters[0] = tline
        else
          new_cmd = RPG::EventCommand.new
          new_cmd.code = 401; new_cmd.indent = cmd.indent; new_cmd.parameters = [tline]
          event.list.insert(i, new_cmd)
        end
        i += 1
      end
      while event.list[i] && event.list[i].code == 401
        event.list[i].parameters[0] = ""; i += 1
      end
      total += 1
    end
  end

  File.binwrite(path, Marshal.dump(data))
  total
rescue => e
  warn "  Error inyectando CommonEvents: #{e.message}"
  0
end

# ─────────────────────────────────────────────────────────────────────────────
# 4. PBS files
# ─────────────────────────────────────────────────────────────────────────────
def inject_pbs(pbs_dir, pbs_entries)
  return 0 if pbs_entries.empty?

  by_file = pbs_entries.group_by { |e| e[:file] }
  total = 0

  by_file.each do |filename, entries|
    path = File.join(pbs_dir, filename)
    next unless File.exist?(path)

    # Index: {pbs_id => {field => reconstructed_translated}}
    idx = {}
    entries.each do |e|
      idx[e[:pbs_id]] ||= {}
      idx[e[:pbs_id]][e[:field]] = reconstruct_entry(e, :translated)
    end

    backup(path)
    lines = File.readlines(path, encoding: "UTF-8")
    current_id = nil
    changed = 0

    lines.map! do |line|
      raw = line.encode("UTF-8", invalid: :replace, undef: :replace)
      if raw.strip =~ /^\[([^\]]+)\]$/
        current_id = $1.strip
      elsif current_id && raw =~ /^(\w+)\s*=\s*(.+)$/
        field = $1.strip
        if idx[current_id] && idx[current_id][field]
          inject_val = idx[current_id][field]
          warn_missing_codes($2.strip, inject_val, "pbs:#{filename}:#{current_id}:#{field}")
          raw = "#{field} = #{inject_val}\n"
          changed += 1
        end
      end
      raw
    end

    File.write(path, lines.join, encoding: "UTF-8")
    total += changed
  end

  total
rescue => e
  warn "  Error inyectando PBS: #{e.message}"
  0
end

# ─────────────────────────────────────────────────────────────────────────────
# 5. Scripts.rxdata — strings hardcodeados
# ─────────────────────────────────────────────────────────────────────────────
TARGET_SCRIPT_NAMES = %w[PlayerBreeding PlayerPokemonPregnancy HornyStatus].freeze

def inject_scripts(scripts_path, script_entries)
  return 0 unless File.exist?(scripts_path) && !script_entries.empty?

  by_script = script_entries.group_by { |e| e[:script] }
  backup(scripts_path)
  data = Marshal.load(File.binread(scripts_path))
  total = 0

  data.each do |entry|
    script_name = entry[1].to_s
    next unless TARGET_SCRIPT_NAMES.any? { |t| script_name.include?(t) }
    next unless by_script.key?(script_name)

    code = Zlib::Inflate.inflate(entry[2]).force_encoding("UTF-8")
    by_script[script_name].each do |e|
      orig = reconstruct_entry(e, :original).encode("UTF-8")
      trad = reconstruct_entry(e, :translated).encode("UTF-8")
      if code.gsub!(orig, trad)
        total += 1
      elsif code.gsub!(orig.gsub("\n", "\\n"), trad.gsub("\n", "\\n"))
        total += 1
      end
    end
    entry[2] = Zlib::Deflate.deflate(code.encode("UTF-8"))
  end

  File.binwrite(scripts_path, Marshal.dump(data))
  total
rescue => e
  warn "  Error inyectando Scripts.rxdata: #{e.message}"
  0
end

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
puts "=== Cargando traducciones desde #{TRANS_DIR} ==="

game_entries   = load_translated(File.join(TRANS_DIR, "messages_game.toml"))
core_entries   = load_translated(File.join(TRANS_DIR, "messages_core.toml"))
map_entries    = load_translated(File.join(TRANS_DIR, "maps.toml"))
ce_entries     = load_translated(File.join(TRANS_DIR, "common_events.toml"))
pbs_entries    = load_translated(File.join(TRANS_DIR, "pbs.toml"))
script_entries = load_translated(File.join(TRANS_DIR, "scripts.toml"))

puts "  messages_game : #{game_entries.size} con traducción"
puts "  messages_core : #{core_entries.size} con traducción"
puts "  maps          : #{map_entries.size} con traducción"
puts "  common_events : #{ce_entries.size} con traducción"
puts "  pbs           : #{pbs_entries.size} con traducción"
puts "  scripts       : #{script_entries.size} con traducción"

total_with_translation = game_entries.size + core_entries.size + map_entries.size +
                         ce_entries.size + pbs_entries.size + script_entries.size
if total_with_translation == 0
  puts "\nNinguna entrada tiene traducción — nada que inyectar."
  exit 0
end

puts
puts "=== Inyectando ==="

n = inject_messages_dat(File.join(DATA_DIR, "messages_game.dat"), game_entries)
puts "  messages_game.dat   : #{n} strings actualizados"

n = inject_messages_dat(File.join(DATA_DIR, "messages_core.dat"), core_entries)
puts "  messages_core.dat   : #{n} strings actualizados"

n = inject_maps(DATA_DIR, map_entries)
puts "  Map*.rxdata         : #{n} diálogos actualizados"

n = inject_common_events(File.join(DATA_DIR, "CommonEvents.rxdata"), ce_entries)
puts "  CommonEvents.rxdata : #{n} diálogos actualizados"

n = inject_pbs(PBS_DIR, pbs_entries)
puts "  PBS files           : #{n} campos actualizados"

n = inject_scripts(File.join(DATA_DIR, "Scripts.rxdata"), script_entries)
puts "  Scripts.rxdata      : #{n} strings actualizados"

puts
puts "━━━ Inyección completa. Los archivos originales tienen backup *.bak ━━━"
puts "Recuerda ejecutar el juego desde la copia virgen para verificar."
