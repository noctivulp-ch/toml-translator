#!/usr/bin/env ruby
# diff_strings.rb — compara dos versiones del juego para detectar cambios de texto
# Uso:
#   ruby Tools/diff_strings.rb /ruta/v0.2.2 /ruta/v0.2.3 [--out diff.toml]
#
# Genera un TOML de diff con secciones [[added]], [[changed]], [[removed]].
# Las entradas [[added]] y [[changed]] tienen translated="" listas para traducir.
# Pasa el resultado a auto_translate.py para traducir solo los strings nuevos:
#   python Tools/auto_translate.py --api ollama translation/diff.toml

require 'zlib'
require 'digest'
require 'fileutils'
require 'set'

# ─────────────────────────────────────────────────────────────────────────────
# Reutilizar stubs y helpers del extractor
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
  class EventCommand; attr_accessor :code, :indent, :parameters; end
  class CommonEvent
    attr_accessor :id, :name, :trigger, :condition, :list
    def initialize; @list = []; end
  end
  class MapInfo; attr_accessor :name, :parent_id, :order, :expanded, :scroll_x, :scroll_y; end
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

def safe_utf8(s)
  s = s.to_s
  if s.encoding == Encoding::UTF_8
    return s if s.valid_encoding?
    return s.encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")
  end
  as_utf8 = s.dup.force_encoding("UTF-8")
  return as_utf8 if as_utf8.valid_encoding?
  s.dup.force_encoding("Windows-1252").encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")
rescue
  s.to_s.encode("UTF-8", invalid: :replace, undef: :replace, replace: "?")
end

def short_id(text)
  Digest::MD5.hexdigest(text.encode("UTF-8", invalid: :replace, undef: :replace))[0, 12]
end

TRANSLATE_IDX_GAME = [3, 6, 9, 11, 15, 16, 17, 22, 23, 24, 26].freeze
TRANSLATE_IDX_CORE = [3, 6, 9, 11, 24, 26].freeze
TARGET_SCRIPT_NAMES = %w[PlayerBreeding PlayerPokemonPregnancy HornyStatus].freeze
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

# ─────────────────────────────────────────────────────────────────────────────
# Extracción completa de un directorio de juego
# ─────────────────────────────────────────────────────────────────────────────
def extract_all_from(game_dir)
  entries = {}  # id => {id:, original:, source:}
  data_dir = File.join(game_dir, "Data")
  pbs_dir  = File.join(game_dir, "PBS")

  # messages_game.dat
  [:game, :core].each do |which|
    dat  = which == :game ? "messages_game.dat" : "messages_core.dat"
    idxs = which == :game ? TRANSLATE_IDX_GAME : TRANSLATE_IDX_CORE
    tag  = which == :game ? "g" : "c"
    path = File.join(data_dir, dat)
    next unless File.exist?(path)
    begin
      data = Marshal.load(File.binread(path))
      if data[0].is_a?(Array)
        data[0].each do |bucket|
          next unless bucket.is_a?(Hash)
          bucket.each_key do |original|
            next unless original.is_a?(String) && original.length >= 5
            id = "#{tag}_d0_#{short_id(original)}"
            entries[id] = { id: id, original: safe_utf8(original), source: dat }
          end
        end
      end
      idxs.each do |idx|
        sec = data[idx]; next unless sec.is_a?(Hash)
        sec.each_key do |original|
          next unless original.is_a?(String) && original.length >= 5
          id = "#{tag}_s#{idx}_#{short_id(original)}"
          entries[id] = { id: id, original: safe_utf8(original), source: dat }
        end
      end
    rescue => e; warn "  Error #{dat}: #{e.message}"; end
  end

  # Map*.rxdata
  map_infos = {}
  mi_path = File.join(data_dir, "MapInfos.rxdata")
  Marshal.load(File.binread(mi_path)).each { |id, info| map_infos[id] = info.name rescue "" } if File.exist?(mi_path)
  Dir.glob(File.join(data_dir, "Map[0-9]*.rxdata")).sort.each do |path|
    map_id = File.basename(path)[/\d+/].to_i
    begin
      map = Marshal.load(File.binread(path))
      map.events.each do |eid, event|
        event.pages.each_with_index do |page, pi|
          buf = nil; buf_lines = []
          page.list.each_with_index do |cmd, ci|
            case cmd.code
            when 101
              entries[buf[:id]] = buf if buf
              ename = safe_utf8(event.respond_to?(:name) ? event.name.to_s : "")
              mname = safe_utf8(map_infos[map_id].to_s)
              buf = { id: "M#{map_id}E#{eid}P#{pi}C#{ci}",
                      original: "", source: File.basename(path) }
              buf_lines = [safe_utf8(cmd.parameters[0])]
            when 401; buf_lines << safe_utf8(cmd.parameters[0]) if buf
            else
              if buf
                buf[:original] = buf_lines.join("\n")
                entries[buf[:id]] = buf unless buf[:original].strip.empty?
                buf = nil; buf_lines = []
              end
            end
          end
          if buf
            buf[:original] = buf_lines.join("\n")
            entries[buf[:id]] = buf unless buf[:original].strip.empty?
          end
        end
      end
    rescue => e; warn "  Error mapa #{map_id}: #{e.message}"; end
  end

  # CommonEvents.rxdata
  ce_path = File.join(data_dir, "CommonEvents.rxdata")
  if File.exist?(ce_path)
    begin
      Marshal.load(File.binread(ce_path)).each do |event|
        next unless event && event.respond_to?(:list) && event.list
        buf = nil; buf_lines = []
        event.list.each_with_index do |cmd, ci|
          case cmd.code
          when 101
            entries[buf[:id]] = buf if buf
            buf = { id: "CE#{event.id}C#{ci}", original: "", source: "CommonEvents.rxdata" }
            buf_lines = [safe_utf8(cmd.parameters[0])]
          when 401; buf_lines << safe_utf8(cmd.parameters[0]) if buf
          else
            if buf
              buf[:original] = buf_lines.join("\n")
              entries[buf[:id]] = buf unless buf[:original].strip.empty?
              buf = nil; buf_lines = []
            end
          end
        end
        if buf; buf[:original] = buf_lines.join("\n"); entries[buf[:id]] = buf unless buf[:original].strip.empty?; end
      end
    rescue => e; warn "  Error CommonEvents: #{e.message}"; end
  end

  # PBS
  PBS_CONFIG.each do |filename, fields|
    path = File.join(pbs_dir, filename)
    next unless File.exist?(path)
    current_id = nil
    File.foreach(path, encoding: "UTF-8") do |raw|
      line = raw.encode("UTF-8", invalid: :replace, undef: :replace).chomp.strip
      next if line.start_with?("#") || line.empty?
      if line =~ /^\[([^\]]+)\]$/; current_id = $1.strip
      elsif current_id && line =~ /^(\w+)\s*=\s*(.+)$/
        field = $1.strip; value = $2.strip
        next unless fields.include?(field) && value.length >= 3
        id = "pbs:#{filename}:#{current_id}:#{field}"
        entries[id] = { id: id, original: value, source: filename }
      end
    end
  end

  # Scripts.rxdata
  scripts_path = File.join(data_dir, "Scripts.rxdata")
  if File.exist?(scripts_path)
    begin
      Marshal.load(File.binread(scripts_path)).each do |entry|
        script_name = entry[1].to_s
        next unless TARGET_SCRIPT_NAMES.any? { |t| script_name.include?(t) }
        code = Zlib::Inflate.inflate(entry[2])
        code.scan(/pbMessage\(\s*["']((?:[^"'\\]|\\.)*?)["']\s*\)/) do |match|
          text = match[0].gsub(/\\n/, "\n").gsub(/\\t/, "\t").gsub(/\\"/, '"').gsub(/\\'/, "'")
          next if text.strip.length < 4
          id = "scr:#{script_name}:#{short_id(text)}"
          entries[id] = { id: id, original: text, source: "Scripts.rxdata" }
        end
      end
    rescue => e; warn "  Error Scripts.rxdata: #{e.message}"; end
  end

  entries
end

# ─────────────────────────────────────────────────────────────────────────────
# Escritura del TOML de diff
# ─────────────────────────────────────────────────────────────────────────────
def toml_str(s)
  s = s.to_s
  if s.include?("\n")
    inner = s.gsub("\\", "\\\\").gsub('"', '\\"')
    "\"\"\"\n#{inner}\"\"\""
  else
    "\"#{s.gsub("\\", "\\\\").gsub('"', '\\"')}\""
  end
end

def write_diff_toml(out_path, added, changed, removed)
  File.open(out_path, "w", encoding: "UTF-8") do |f|
    f.puts "# Diff de traducción — generado por diff_strings.rb"
    f.puts "# [[added]]   = strings nuevos (traducir)"
    f.puts "# [[changed]] = strings cuyo original cambió (revisar traducción anterior)"
    f.puts "# [[removed]] = strings que ya no existen (traducciones obsoletas)"
    f.puts

    unless added.empty?
      f.puts "# ─── NUEVOS (#{added.size}) ───────────────────────────────────────"
      added.each do |e|
        f.puts "[[added]]"
        f.puts "id         = #{toml_str(e[:id])}"
        f.puts "source     = #{toml_str(e[:source])}"
        f.puts "original   = #{toml_str(e[:original])}"
        f.puts "translated = \"\""
        f.puts
      end
    end

    unless changed.empty?
      f.puts "# ─── CAMBIADOS (#{changed.size}) ───────────────────────────────────"
      changed.each do |e|
        f.puts "[[changed]]"
        f.puts "id           = #{toml_str(e[:id])}"
        f.puts "source       = #{toml_str(e[:source])}"
        f.puts "original_old = #{toml_str(e[:original_old])}"
        f.puts "original_new = #{toml_str(e[:original_new])}"
        f.puts "translated   = \"\""
        f.puts
      end
    end

    unless removed.empty?
      f.puts "# ─── ELIMINADOS (#{removed.size}) ──────────────────────────────────"
      removed.each do |e|
        f.puts "# [[removed]] id=#{e[:id]} source=#{e[:source]}"
      end
      f.puts
    end
  end
end

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
dir_old = ARGV[0]
dir_new = ARGV[1]
out_idx = ARGV.index("--out")
out_path = out_idx ? ARGV[out_idx + 1] : File.join(dir_new || ".", "translation", "diff.toml")

if dir_old.nil? || dir_new.nil?
  puts "Uso: ruby Tools/diff_strings.rb /ruta/v_old /ruta/v_new [--out diff.toml]"
  exit 1
end

puts "Extrayendo strings de #{File.basename(dir_old)} ..."
old_entries = extract_all_from(dir_old)
puts "  #{old_entries.size} entries en version antigua"

puts "Extrayendo strings de #{File.basename(dir_new)} ..."
new_entries = extract_all_from(dir_new)
puts "  #{new_entries.size} entries en version nueva"

# Comparar
added_ids   = new_entries.keys.to_set - old_entries.keys.to_set
removed_ids = old_entries.keys.to_set - new_entries.keys.to_set
changed_ids = (new_entries.keys.to_set & old_entries.keys.to_set).select do |id|
  new_entries[id][:original] != old_entries[id][:original]
end.to_set

added   = added_ids.map   { |id| new_entries[id] }.sort_by { |e| e[:id] }
removed = removed_ids.map { |id| old_entries[id] }.sort_by { |e| e[:id] }
changed = changed_ids.map do |id|
  new_entries[id].merge(
    original_old: old_entries[id][:original],
    original_new: new_entries[id][:original]
  )
end.sort_by { |e| e[:id] }

# Detectar archivos nuevos en Data/ y PBS/
new_data_files = (Dir.glob(File.join(dir_new, "Data", "*.rxdata")) +
                  Dir.glob(File.join(dir_new, "Data", "*.dat")) +
                  Dir.glob(File.join(dir_new, "PBS", "*.txt"))).map { |p| File.basename(p) }.to_set
old_data_files = (Dir.glob(File.join(dir_old, "Data", "*.rxdata")) +
                  Dir.glob(File.join(dir_old, "Data", "*.dat")) +
                  Dir.glob(File.join(dir_old, "PBS", "*.txt"))).map { |p| File.basename(p) }.to_set
truly_new_files = new_data_files - old_data_files

FileUtils.mkdir_p(File.dirname(out_path))
write_diff_toml(out_path, added, changed, removed)

puts
puts "━━━ Diff completo ━━━"
puts "  Strings nuevos    : #{added.size}"
puts "  Strings cambiados : #{changed.size}"
puts "  Strings eliminados: #{removed.size}"
puts "  Archivo diff      : #{out_path}"
unless truly_new_files.empty?
  puts "  Archivos nuevos en versión #{File.basename(dir_new)}:"
  truly_new_files.sort.each { |f| puts "    + #{f}" }
end
puts
puts "Para traducir los strings nuevos:"
puts "  python Tools/auto_translate.py --api ollama #{out_path}"
